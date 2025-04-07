import pymongo
import datetime
import smtplib
import os
import logging
import pytz
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/gmto/emf_logs/weather_report.log'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# MongoDB Connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://172.18.10.161:27017/')
DB_NAME = os.getenv('DB_NAME', 'gmt_tele_1')
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'tele_events')

# Email Configuration
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', 'gelhalabi@gmto.org').split(',')

# Add timezone configuration
CHILE_TZ = pytz.timezone('America/Santiago')

# Add type code mapping
TYPE_CODE_MAP = {
    'WIND_DIRECTION': 'WD',
    'WIND_SPEED': 'WS',
    'PRESSURE': 'P',
    'DEW_POINT': 'DEW',
    'TEMPERATURE': 'T',
    'HUMIDITY': 'H',
    'PRECIPITATION': 'PREC',
    'BAROMETRIC_TREND': 'BT'
}

# Add full type name mapping
TYPE_NAMES = {
    'T': 'Temperature',
    'WS': 'Wind Speed',
    'PREC': 'Precipitation',
    'DEW': 'Dew Point',
    'H': 'Humidity',
    'P': 'Pressure',
    'WD': 'Wind Direction',
    'BT': 'Barometric Trend',
}

# Constants for sensor heights
SENSOR_HEIGHTS = ['12m', '24m', '36m', '48m']

# Error handling for MongoDB connection
def fetch_weather_data():
    try:
        logging.info("Connecting to MongoDB...")
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        logging.info("Successfully connected to MongoDB")
        
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        now = datetime.datetime.now(datetime.timezone.utc)
        start_time = now - datetime.timedelta(days=1)
        timestamp_ns = int(start_time.timestamp() * 1e9)
        
        # Query for all EMF weather control records from past day
        query = {
            "ts": {"$gte": timestamp_ns},
            "src": {"$regex": "emf_weather_ctrl"}
        }
        
        logging.info(f"Querying EMF weather records from {start_time} to {now}")
        count = collection.count_documents(query)
        logging.info(f"Found {count} EMF weather records")
        
        if count == 0:
            logging.warning("No EMF weather records found in the specified period")
            return []
            
        # Get all records with sorting, no limit
        weather_data = list(collection.find(query).sort("ts", -1))
        
        client.close()
        logging.info(f"Retrieved all {len(weather_data)} EMF weather records for the past 24 hours")
        return weather_data
        
    except Exception as e:
        logging.error(f"Unexpected error in fetch_weather_data: {e}")
        logging.error(f"Error type: {type(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        raise

# Format the data into a log file
def generate_weather_log(data):
    try:
        logging.info("Generating weather log...")
        now = datetime.datetime.now(CHILE_TZ)  # Use Chile timezone
        log_filename = f"/home/gmto/emf_logs/emf_weather_log_{now.strftime('%Y%m%d')}.txt"
        
        os.makedirs(os.path.dirname(log_filename), exist_ok=True)

        with open(log_filename, "w") as log_file:
            log_file.write("Date; Type; Value[0]; Value[1]; Value[2]; Value[3]; Valid[0]; Valid[1]; Valid[2]; Valid[3]\n")
            
            for entry in data:
                # Convert UTC timestamp to Chile time
                utc_dt = datetime.datetime.utcfromtimestamp(entry["ts"] / 1e9)
                utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
                chile_dt = utc_dt.astimezone(CHILE_TZ)
                ts = chile_dt.strftime('%Y/%m/%d %H:%M:%S')
                
                src = entry["src"]
                value = entry["value"]
                
                # Extract and map type code to shorter version
                type_code = src.split('/')[-2].upper()
                type_code = TYPE_CODE_MAP.get(type_code, type_code)  # Use mapping or original if not found
                
                # Format values and valid flags
                if isinstance(value, dict) and 'values' in value:
                    # Get values from the 'values' key
                    values = [f"{v:.2f}" if isinstance(v, float) else str(v) for v in value.get('values', [0]*4)]
                    # Simplify valid flags to YES/NO
                    valids = ['NO' if v != 'VALID' else 'YES' for v in value.get('valid', ['YES']*4)]
                    
                    values_str = ','.join(values)
                    valids_str = ','.join(valids)
                    log_file.write(f"{ts}; {type_code}; {values_str}; {valids_str}\n")
        
        logging.info(f"Weather log generated: {log_filename}")
        return log_filename
    except Exception as e:
        logging.error(f"Error generating weather log: {e}")
        raise

def generate_hourly_stats(data):
    """Generate hourly statistics for each measurement type"""
    hourly_data = {}
    invalid_counts = {}
    
    for entry in data:
        ts = datetime.datetime.utcfromtimestamp(entry["ts"] / 1e9)
        ts = ts.replace(tzinfo=pytz.UTC).astimezone(CHILE_TZ)
        # Round to nearest hour
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        
        type_code = entry["src"].split('/')[-2].upper()
        value = entry["value"]
        
        if isinstance(value, dict) and 'values' in value:
            # Initialize data structures if needed
            if type_code not in hourly_data:
                hourly_data[type_code] = {}
            if type_code not in invalid_counts:
                invalid_counts[type_code] = [0, 0, 0, 0]  # One counter per height
                
            # Count invalid measurements
            for i, valid_flag in enumerate(value.get('valid', [])):
                if valid_flag != 'VALID':
                    invalid_counts[type_code][i] += 1
            
            # Store hourly data
            if hour_ts not in hourly_data[type_code]:
                values = value.get('values', [])
                # For wind direction, replace invalid with 'INV'
                if type_code == 'WIND_DIRECTION':
                    values = ['INV' if value.get('valid', ['VALID']*4)[i] != 'VALID' else v 
                            for i, v in enumerate(values)]
                hourly_data[type_code][hour_ts] = values
    
    return hourly_data, invalid_counts

def calculate_daily_stats(data):
    """Calculate daily statistics for weather measurements"""
    # Initialize lists of tuples (value, timestamp)
    wind_speeds = []
    temperatures = []
    humidities = []
    wind_directions = []
    
    for entry in data:
        type_code = entry["src"].split('/')[-2].upper()
        value = entry["value"]
        
        if isinstance(value, dict) and 'values' in value:
            # Convert timestamp to Chile time
            ts = datetime.datetime.utcfromtimestamp(entry["ts"] / 1e9)
            ts = ts.replace(tzinfo=pytz.UTC).astimezone(CHILE_TZ)
            
            # Only consider valid measurements
            valid_values = [(v, ts) for i, v in enumerate(value.get('values', [])) 
                          if value.get('valid', ['VALID']*4)[i] == 'VALID']
            
            if valid_values:
                if type_code == 'WIND_SPEED':
                    wind_speeds.extend(valid_values)
                elif type_code == 'TEMPERATURE':
                    temperatures.extend(valid_values)
                elif type_code == 'HUMIDITY':
                    humidities.extend(valid_values)
                elif type_code == 'WIND_DIRECTION':
                    wind_directions.extend(valid_values)
    
    # Calculate statistics with timestamps
    stats = {
        'wind_speed_max': max(wind_speeds, key=lambda x: x[0]) if wind_speeds else ('N/A', None),
        'wind_speed_min': min(wind_speeds, key=lambda x: x[0]) if wind_speeds else ('N/A', None),
        'wind_speed_avg': sum(v[0] for v in wind_speeds)/len(wind_speeds) if wind_speeds else 'N/A',
        'temp_max': max(temperatures, key=lambda x: x[0]) if temperatures else ('N/A', None),
        'temp_min': min(temperatures, key=lambda x: x[0]) if temperatures else ('N/A', None),
        'humidity_max': max(humidities, key=lambda x: x[0]) if humidities else ('N/A', None),
        'humidity_min': min(humidities, key=lambda x: x[0]) if humidities else ('N/A', None),
        'wind_dir_avg': sum(v[0] for v in wind_directions)/len(wind_directions) if wind_directions else 'N/A'
    }
    
    return stats

def format_email_body(hourly_data, invalid_counts):
    """Format the email body with statistics"""
    now = datetime.datetime.now(CHILE_TZ)
    body = [f"Weather data {now.strftime('%Y/%m/%d')}\n\n"]
    
    # Add daily statistics section
    stats = calculate_daily_stats(weather_data)
    body.append("Daily Statistics\n----------------\n\n")
    
    # Helper function to format value with timestamp
    def format_stat_with_time(stat, unit):
        if isinstance(stat, tuple):
            value, timestamp = stat
            if isinstance(value, (int, float)) and timestamp:
                return f"{value:.2f} {unit} at {timestamp.strftime('%H:%M:%S')}"
        return "N/A"
    
    body.append(f"Maximum Wind Speed: {format_stat_with_time(stats['wind_speed_max'], 'm/s')}\n")
    body.append(f"Minimum Wind Speed: {format_stat_with_time(stats['wind_speed_min'], 'm/s')}\n")
    body.append(f"Average Wind Speed: {stats['wind_speed_avg']:.2f} m/s\n" if isinstance(stats['wind_speed_avg'], (int, float)) else "Average Wind Speed: N/A\n")
    body.append(f"Maximum Temperature: {format_stat_with_time(stats['temp_max'], '°C')}\n")
    body.append(f"Minimum Temperature: {format_stat_with_time(stats['temp_min'], '°C')}\n")
    body.append(f"Maximum Relative Humidity: {format_stat_with_time(stats['humidity_max'], '%')}\n")
    body.append(f"Minimum Relative Humidity: {format_stat_with_time(stats['humidity_min'], '%')}\n")
    body.append(f"Average Wind Direction: {stats['wind_dir_avg']:.2f}°\n" if isinstance(stats['wind_dir_avg'], (int, float)) else "Average Wind Direction: N/A\n")
    body.append("\n")
    
    # Invalid data summary
    body.append("Sensors that had INVALID data\n-----------------------------\n\n")
    for type_code, counts in sorted(invalid_counts.items()):
        display_name = TYPE_CODE_MAP.get(type_code, type_code).replace('_', ' ').title()
        for height, count in zip(SENSOR_HEIGHTS, counts):
            if count > 0:
                body.append(f"{display_name}[{height}]: {count} invalid samples\n")
    
    # Hourly records for each type
    for type_code, hours in sorted(hourly_data.items()):
        display_name = TYPE_NAMES.get(TYPE_CODE_MAP.get(type_code, type_code), type_code)
        body.append(f"\n\n{display_name} records\n-------------------\n\n")
        
        for hour in sorted(hours.keys()):
            values = hours[hour]
            formatted_values = []
            for v in values:
                if v == 'INV':
                    formatted_values.append(f"{v:>7}")
                elif isinstance(v, float):
                    formatted_values.append(f"{v:>7.2f}")  # Format to 2 decimal places
                else:
                    formatted_values.append(f"{v:>7}")
            
            body.append(f"        {hour.strftime('%Y/%m/%d %H:%M:%S')}    {' '.join(formatted_values)}\n")
    
    return "".join(body)

# Send email with the log file
def send_email(log_filename):
    try:
        logging.info("Sending email...")
        
        # Generate statistics for email body
        hourly_data, invalid_counts = generate_hourly_stats(weather_data)  # Add weather_data as global
        email_body = format_email_body(hourly_data, invalid_counts)
        
        msg = MIMEMultipart()
        now = datetime.datetime.now(CHILE_TZ)
        msg["Subject"] = f"EMF Weather Report - {now.strftime('%Y-%m-%d')}"
        msg["From"] = EMAIL_SENDER
        msg["To"] = ", ".join(EMAIL_RECIPIENTS)
        
        # Add the detailed report to email body
        msg.attach(MIMEText(email_body, "plain"))
        
        # Attach the log file
        with open(log_filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={os.path.basename(log_filename)}"
        )
        msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENTS, msg.as_string())
        
        logging.info("Email sent successfully with attachment")
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        raise

# Main execution
if __name__ == "__main__":
    try:
        logging.info("Starting weather report generation...")
        weather_data = fetch_weather_data()  # Make this global for email body generation
        if not weather_data:
            logging.warning("No weather data found for the specified period")
            exit(0)
            
        log_file = generate_weather_log(weather_data)
        send_email(log_file)
        logging.info("Weather report process completed successfully")
    except Exception as e:
        logging.error(f"Weather report process failed: {e}")
        raise
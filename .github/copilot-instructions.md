# Copilot Instructions for GMT EMF Weather Report System

## Project Overview

This repository contains an automated weather monitoring system that queries MongoDB for telemetry data from the GMT (Giant Magellan Telescope) EMF weather control system and dust sensors, generates daily reports, and emails them to stakeholders. The script runs as a cron job at 02:55 daily (Chile time).

**Recent Development**: Dust sensor data integration completed - system now reports both weather and particulate matter data.

## Architecture & Data Flow

**MongoDB → Python Script → Log Files + Email Report**

1. **Data Source**: MongoDB (`gmt_tele_1.tele_events`) stores telemetry events with nanosecond timestamps
2. **Query Pattern**: Fetches 24 hours of records matching `src: {$regex: "emf_(weather|dust)_ctrl"}`
3. **Processing**: 
   - Weather: Aggregates sensor data from 4 heights (12m, 24m, 36m, 48m) for 8 measurement types
   - Dust: Aggregates particle counts across 8 size bins from 2 sensors (MT1, MT2)
4. **Output**: 
   - Daily weather log: `/home/gmto/emf_logs/emf_weather_log_YYYYMMDD.txt` (CSV format)
   - Daily dust log: `/home/gmto/emf_logs/emf_dust_log_YYYYMMDD.txt` (CSV format)
   - Email report with statistics and hourly summaries for both types

## Key Conventions

### Timezone Handling
- **Critical**: All timestamps are stored in UTC in MongoDB but displayed in Chile time (`America/Santiago`)
- Use `pytz.timezone('America/Santiago')` for all user-facing timestamps
- MongoDB timestamps are in **nanoseconds** (multiply by 1e9, divide when reading)

### Data Structure Pattern
```python
# MongoDB document structure for weather events:
{
    "ts": 1234567890000000000,  # Nanosecond timestamp
    "src": "emf_weather_ctrl/temperature/...",  # Path-like sensor ID
    "value": {
        "values": [12.5, 13.1, 14.2, 15.0],  # 4 sensor heights
        "valid": ["VALID", "VALID", "INVALID", "VALID"]  # Validity flags (array)
    }
}

# MongoDB document structure for dust sensor events:
{
    "ts": 1766009313547613400,  # Nanosecond timestamp
    "src": "emf_dust_ctrl/o/mt1_particles/value",  # Sensor path (mt1 or mt2)
    "value": {
        "values": [218, 111, 59, 29, 9, 2, 2, 0],  # 8 particle size bins
        "valid": "VALID"  # Validity flag (single string, not array!)
    }
}
```

**Critical Differences**:
- Weather sensors: 4 values (heights), array of valid flags
- Dust sensors: 8 values (particle bins), single valid string
- Weather validation: Check each element `!= 'VALID'`
- Dust validation: Check string `== 'VALID'`

### Type Code Mapping
The script uses **abbreviated codes** in output (not the full names from `src` field):
- Weather: `TEMPERATURE` → `T`, `WIND_SPEED` → `WS`, `HUMIDITY` → `H`, etc.
- Dust: `MT1_PARTICLES` → `DUST1`, `MT2_PARTICLES` → `DUST2`
- See `TYPE_CODE_MAP` and `TYPE_NAMES` dictionaries for full mappings

### Dust Sensor Particle Bins
8 size bins tracked by dust sensors (defined in `DUST_PARTICLE_BINS`):
- 0.3μm, 0.5μm, 0.7μm, 1.0μm, 2.0μm, 3.0μm, 5.0μm, 10.0μm
- Values represent particle counts per bin
- Statistics: Max count per bin (with timestamp), hourly averages per bin

## Environment Configuration

**Required `.env` variables** (Gmail preferred for email delivery):
```bash
MONGO_URI=mongodb://172.18.10.161:27017/  # Internal MongoDB server
SMTP_SERVER=smtp.gmail.com                # Gmail SMTP (preferred)
SMTP_PORT=587                             # TLS port
EMAIL_SENDER=gmt.emf@gmail.com            # Gmail account for sending
EMAIL_PASSWORD=<app-specific-password>     # Gmail app password (not regular password)
EMAIL_RECIPIENTS=user1@gmto.org,user2@gmto.org  # Comma-separated
```

**Note**: While Microsoft SMTP was tested, Gmail is the production email provider.

## Development Workflow

### Running Locally
```bash
# Ensure you're in the script directory
cd /home/gmto/scripts

# Load environment variables from .env
python3 emf_cron_weather_report.py
```

### Testing Email Changes
- Recipients can be temporarily overridden in `.env` (see commented line)
- Test with single recipient before deploying to production

### Debugging
- Logs go to **both** `/home/gmto/emf_logs/weather_report.log` and stdout
- Check cron execution: `grep weather /var/log/cron` or check log file
- Verify MongoDB connectivity: `pymongo.MongoClient(...).server_info()` will raise exception if unreachable

## Cron Schedule
```cron
55 02 * * * /usr/bin/python3 /home/gmto/scripts/emf_cron_weather_report.py
```
Runs daily at 02:55 (system time should be set to Chile timezone or use explicit TZ in crontab)

## Common Pitfalls

1. **Invalid Data Handling**: 
   - Weather: Check array elements `!= 'VALID'` for each height
   - Dust: Check single string `!= 'VALID'` for entire reading
2. **Empty Result Sets**: Script exits gracefully with warning if no data found (check MongoDB connectivity first)
3. **Email Authentication**: Gmail requires app-specific passwords (not regular account password)
4. **Timestamp Precision**: MongoDB stores nanosecond timestamps; Python's `timestamp()` returns seconds
5. **Global Variables**: `weather_data` and `dust_data` must be global for email functions to access
6. **Data Splitting**: Main execution splits combined data by checking if `'emf_weather_ctrl'` or `'emf_dust_ctrl'` in src field

## Key Files & Directories

- `emf_cron_weather_report.py` - Main script (single-file application handling both weather and dust)
- `.env` - Credentials and configuration (never commit with real credentials)
- `/home/gmto/emf_logs/` - Output directory for logs and daily files:
  - `emf_weather_log_YYYYMMDD.txt` - Weather sensor data (4 columns)
  - `emf_dust_log_YYYYMMDD.txt` - Dust sensor data (8 columns)
  - `weather_report.log` - Application log file

## Code Architecture

### Key Functions
- `fetch_weather_data()` - Queries MongoDB for both weather and dust data
- `generate_weather_log(data)` - Creates CSV log for weather sensors (4-height format)
- `generate_dust_log(data)` - Creates CSV log for dust sensors (8-bin format)
- `generate_hourly_stats(data)` - Weather hourly aggregation
- `generate_dust_hourly_stats(data)` - Dust hourly averages per bin
- `calculate_daily_stats(data)` - Weather min/max/avg statistics
- `calculate_dust_daily_stats(data)` - Max particle count per bin with timestamps
- `format_email_body(...)` - Combines weather and dust sections in email
- `send_email(weather_log, dust_log)` - Attaches both log files to email

## Git Workflow

- **Default branch**: `gmail_email` (production branch with Gmail email delivery)
- **Current branch**: `feature/dust-sensor--from-gmail_email` - Dust sensor integration (ready to merge)
- **Branch naming**: Use descriptive names like `feature/[feature-name]--from-[base-branch]`
- Historical context: Tested Microsoft SMTP but reverted to Gmail as preferred provider

## Adding New Sensor Types

When integrating new sensors (completed example: dust sensor):
1. Add sensor type to `TYPE_CODE_MAP` dictionary with abbreviated code
2. Add display name to `TYPE_NAMES` dictionary
3. Update query pattern in `fetch_weather_data()` if sensor uses different `src` path structure
4. Create separate log generation function if data structure differs (like dust sensors)
5. Create separate stats functions for different data formats (array vs single value validation)
6. Update `format_email_body()` to include new sensor in report with conditional sections
7. Update main execution to split and process new sensor data type
8. Test with single recipient in `.env` before full deployment

### Dust Sensor Implementation Reference
- See `generate_dust_log()`, `generate_dust_hourly_stats()`, and `calculate_dust_daily_stats()` for pattern
- Key difference: 8 values instead of 4, string validation instead of array validation
- Separate log file approach maintains clean CSV structure
- Email formatting uses particle bin labels for clarity

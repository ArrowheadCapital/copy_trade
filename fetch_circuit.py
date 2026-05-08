import json
from time import perf_counter
import redis
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()
redis_client = None


def get_redis_client(host="100.103.231.7", port=6379, db=1):
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
        )
        redis_client.ping()
    return redis_client


def get_exchange_instrument_id(description, df):
    """
    Filter options_instruments.csv by description and return ExchangeInstrumentID.
    
    Args:
        description (str): The description to match in the Description column
        
    Returns:
        int or None: The ExchangeInstrumentID if found, None otherwise
    """
    try:
        # Filter by Description column
        filtered = df[df['Description'].astype(str).str.strip() == str(description).strip()]
        
        if filtered.empty:
            print(f"No instrument found with description: {description}")
            return None
        
        # Return the first ExchangeInstrumentID found
        return int(filtered.iloc[0]['ExchangeInstrumentID'])
    
    except Exception as e:
        print(f"Error in get_exchange_instrument_id: {e}")
        return None

def get_circuit_limits(instrument_id, host="100.103.231.7", port=6379, db=1):
    """
    Fetch circuit limits (UC and LC) for a given instrument ID from Redis.
    
    Args:
        instrument_id (int): The ExchangeInstrumentID
        host (str): Redis host (default: DESKTOP-CLI5HO6)
        port (int): Redis port (default: 6379)
        db (int): Redis DB index (default: 1)
        
    Returns:
        dict: Dictionary with 'UC' and 'LC' keys, or None if not found
    """
    try:
        client = get_redis_client(host=host, port=port, db=db)
        
        key = f"cache:CIRCUIT_{instrument_id}"
        raw_value = client.get(key)
        
        if raw_value is None:
            print(f"No circuit data found for instrument ID: {instrument_id}")
            return None
        
        try:
            data = json.loads(raw_value)
            result = {
                'ts': data.get('ts'),
                'UC': data.get('UC'),
                'LC': data.get('LC')
            }
            return result
        except json.JSONDecodeError:
            print(f"Error parsing circuit data for instrument ID: {instrument_id}")
            return None
            
    except Exception as e:
        print(f"Error in get_circuit_limits: {e}")
        return None

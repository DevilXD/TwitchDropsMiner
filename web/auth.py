"""
Authentication middleware for the Twitch Drops Miner web interface.
Handles user authentication and API token management using Argon2 and JWT.
"""
import os
import hashlib
import json
import secrets
import time
import datetime
from functools import wraps
from flask import request, jsonify, redirect, url_for
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
CREDENTIALS_PATH = os.path.join(DATA_DIR, 'credentials.json')

# JWT settings - get secret from environment variable or generate and save to .env file
JWT_SECRET = os.environ.get('JWT_SECRET')
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    env_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
    
    # Read current .env file
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            env_content = f.read()
        
        # Check if JWT_SECRET line exists
        if 'JWT_SECRET=' in env_content:
            # Replace existing empty JWT_SECRET line
            env_content = env_content.replace('JWT_SECRET=', f'JWT_SECRET={JWT_SECRET}')
        else:
            # Append JWT_SECRET to the end of the file
            env_content += f"\n# JWT Authentication Secret\nJWT_SECRET={JWT_SECRET}\n"
        
        # Write updated content back to .env file
        with open(env_path, 'w') as f:
            f.write(env_content)
            
        print(f"Generated and saved JWT secret to .env file: {JWT_SECRET[:8]}...{JWT_SECRET[-8:]}")
    else:
        # .env file doesn't exist, just use the generated secret this time
        print(f"WARNING: .env file not found. Using generated JWT secret: {JWT_SECRET[:8]}...{JWT_SECRET[-8:]}")
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_DAYS = 7  # Token expires after 7 days

# Argon2 hasher
ph = PasswordHasher()

def init_credentials():
    """Initialize credentials file if it doesn't exist"""
    if not os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH, 'w') as f:
            json.dump({
                "users": [],
                "setup_complete": False
            }, f)
        return False
    
    with open(CREDENTIALS_PATH, 'r') as f:
        credentials = json.load(f)
    
    return credentials.get("setup_complete", False)

# No longer needed since we're using JWT

def is_setup_needed():
    """Check if initial setup is needed"""
    return not init_credentials()

def create_user(username, password):
    """Create a new user with the given credentials"""
    if not username or not password:
        return False, "Username and password are required"
    
    # Check if file exists
    init_credentials()
    
    with open(CREDENTIALS_PATH, 'r') as f:
        credentials = json.load(f)
    
    # Check if setup is already complete and user is trying to create new account
    if credentials.get("setup_complete", False):
        # Only allow if there are no users yet (special case)
        if credentials.get("users", []):
            return False, "Setup already complete"
    
    # Check if username exists
    for user in credentials.get("users", []):
        if user["username"] == username:
            return False, "Username already exists"
    
    # Create user with Argon2 hashed password
    user = {
        "username": username,
        "password": ph.hash(password),  # Using Argon2 for password hashing
        "created_at": time.time()
    }
    
    credentials["users"] = credentials.get("users", []) + [user]
    credentials["setup_complete"] = True
    
    with open(CREDENTIALS_PATH, 'w') as f:
        json.dump(credentials, f)
    
    return True, "User created successfully"

def validate_credentials(username, password):
    """Validate username and password using Argon2"""
    if not os.path.exists(CREDENTIALS_PATH):
        return False, "No users defined"
    
    with open(CREDENTIALS_PATH, 'r') as f:
        credentials = json.load(f)
    
    for user in credentials.get("users", []):
        if user["username"] == username:
            try:
                # Verify password hash using Argon2
                ph.verify(user["password"], password)
                # If needed, we can implement password rehashing here
                # if ph.check_needs_rehash(user["password"]):
                #     user["password"] = ph.hash(password)
                #     # Save updated hash
                return True, "Authentication successful"
            except VerifyMismatchError:
                return False, "Invalid password"
    
    return False, "User not found"

def generate_token(username):
    """Generate a new JWT token for the user"""
    # Calculate expiry time (7 days from now)
    expiry = datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXPIRY_DAYS)
    expiry_timestamp = int(expiry.timestamp())
    
    # Prepare token payload
    payload = {
        "username": username,
        "iat": int(time.time()),  # Issued at time
        "exp": expiry_timestamp,  # Expiry time
        "jti": secrets.token_hex(16),  # JWT unique identifier
    }
    
    # Create JWT token
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    return token, expiry_timestamp

def validate_token(token):
    """Validate a JWT token and check it's not blacklisted"""
    try:
        # Decode and verify the JWT token
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Check if token is blacklisted
        jti = payload.get("jti")
        if jti:
            blacklist_path = init_blacklist()
            if os.path.exists(blacklist_path):
                with open(blacklist_path, 'r') as f:
                    blacklist_data = json.load(f)
                
                if jti in blacklist_data.get("blacklisted_tokens", {}):
                    return False, "Token revoked"
        
        # Return the username from the payload
        return True, payload.get("username")
    except jwt.ExpiredSignatureError:
        return False, "Token expired"
    except jwt.InvalidTokenError:
        return False, "Invalid token"
    except Exception as e:
        return False, str(e)

def init_blacklist():
    """Initialize blacklist file if it doesn't exist"""
    blacklist_path = os.path.join(DATA_DIR, 'blacklist.json')
    if not os.path.exists(blacklist_path):
        with open(blacklist_path, 'w') as f:
            json.dump({
                "blacklisted_tokens": {},
                "last_cleanup": int(time.time())
            }, f)
    return blacklist_path

def clean_blacklist(blacklist_data):
    """Clean up expired tokens from blacklist"""
    current_time = int(time.time())
    last_cleanup = blacklist_data.get("last_cleanup", 0)
    
    # Only clean up once a day
    if current_time - last_cleanup < 86400:
        return blacklist_data
        
    # Remove expired entries
    for jti, expiry in list(blacklist_data.get("blacklisted_tokens", {}).items()):
        if current_time > expiry:
            del blacklist_data["blacklisted_tokens"][jti]
    
    blacklist_data["last_cleanup"] = current_time
    return blacklist_data

def revoke_token(token):
    """Add a JWT token to the blacklist"""
    try:
        # First, verify the token is valid
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Get the token's unique identifier and expiry
        jti = payload.get("jti")
        exp = payload.get("exp")
        
        if not jti:
            return False
            
        # Get blacklist path
        blacklist_path = init_blacklist()
        
        # Read blacklist
        with open(blacklist_path, 'r') as f:
            blacklist_data = json.load(f)
        
        # Clean blacklist
        blacklist_data = clean_blacklist(blacklist_data)
        
        # Add token to blacklist
        blacklist_data["blacklisted_tokens"][jti] = exp
        
        # Save blacklist
        with open(blacklist_path, 'w') as f:
            json.dump(blacklist_data, f)
        
        return True
    except Exception:
        # If token is invalid, no need to blacklist it
        return False

def auth_required(f):
    """Decorator to require authentication for API routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get token from Authorization header
        token = None
        if 'Authorization' in request.headers:
            auth = request.headers['Authorization']
            if auth.startswith('Bearer '):
                token = auth[7:]  # Remove 'Bearer ' prefix
        
        # If no token was provided
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Validate token
        valid, username_or_error = validate_token(token)
        if not valid:
            return jsonify({'error': username_or_error}), 401
        
        # Add username to kwargs
        kwargs['username'] = username_or_error
        return f(*args, **kwargs)
    
    return decorated

def login_required(f):
    """Decorator to redirect unauthenticated users to login page for web routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get token from session or cookie
        token = request.cookies.get('auth_token')
        
        # If no token was provided
        if not token:
            return redirect(url_for('login'))
        
        # Validate token
        valid, username_or_error = validate_token(token)
        if not valid:
            return redirect(url_for('login'))
        
        # Add username to kwargs
        kwargs['username'] = username_or_error
        return f(*args, **kwargs)
    
    return decorated

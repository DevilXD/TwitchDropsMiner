#!/usr/bin/env python3
"""
Generate a new JWT secret and update the .env file.
This script is useful for rotating the JWT secret periodically.
"""
import os
import secrets
from dotenv import load_dotenv

def main():
    # Generate new secret
    new_secret = secrets.token_hex(32)
    print(f"Generated new JWT secret")
    
    # Find .env file
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    
    if not os.path.exists(env_path):
        print(f"ERROR: .env file not found at {env_path}")
        print(f"Creating a new .env file with the JWT secret.")
        with open(env_path, 'w') as f:
            f.write(f"# JWT Authentication Secret\nJWT_SECRET={new_secret}\n")
        return
    
    # Read current .env file
    with open(env_path, 'r') as f:
        env_content = f.read()
    
    # Check if JWT_SECRET line exists
    if 'JWT_SECRET=' in env_content:
        # Replace existing JWT_SECRET line
        lines = env_content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('JWT_SECRET='):
                lines[i] = f'JWT_SECRET={new_secret}'
                break
        
        # Write updated content back to .env file
        with open(env_path, 'w') as f:
            f.write('\n'.join(lines))
    else:
        # Append JWT_SECRET to the end of the file
        with open(env_path, 'a') as f:
            f.write(f"\n# JWT Authentication Secret\nJWT_SECRET={new_secret}\n")
    
    print(f"JWT secret has been updated in {env_path}")
    print("NOTE: This will invalidate all existing login sessions. Users will need to log in again.")

if __name__ == "__main__":
    main()

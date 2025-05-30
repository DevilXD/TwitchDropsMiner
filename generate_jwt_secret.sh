#!/bin/bash
# Generate a new JWT secret and update the .env file

python3 generate_jwt_secret.py
echo "Press Enter to continue..."
read

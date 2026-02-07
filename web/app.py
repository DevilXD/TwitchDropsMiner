from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
from time import sleep
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request, redirect, url_for, make_response
from flask_cors import CORS
import os
import sys
import logging
import time
import requests
import json

# Add parent directory to path for imports
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)

# Import from main project
from constants import State
from utils import Game, create_nonce, CHARS_HEX_LOWER
from version import __version__

# Make sure the current directory is in the path so we can import auth.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import auth module (from the web directory)
from auth import is_setup_needed, create_user, validate_credentials, generate_token, validate_token, revoke_token, auth_required, login_required


# Global reference to the TDM instance - will be set by the main app
tdm_instance = None
main_event_loop = None

# Initialize the event loop reference
def initialize(loop, twitch_instance):
    global tdm_instance, main_event_loop
    tdm_instance = twitch_instance
    main_event_loop = loop


def _get_gui():
    """Get the GUI instance from the twitch client.
    In headless/web mode this is a DummyGUI that captures real data.
    Returns None if the miner isn't initialized yet."""
    if tdm_instance is not None and hasattr(tdm_instance, 'gui'):
        return tdm_instance.gui
    return None

# Configure Flask app
app = Flask(__name__, 
    static_folder='static',
    template_folder='templates')
CORS(app)
app.config['JSON_SORT_KEYS'] = False

# Set up logging
logger = logging.getLogger('web_interface')
logger.setLevel(logging.INFO)


@app.route('/login')
def login():
    """Render the login page"""
    return render_template('login.html')

@app.route('/')
@login_required
def index(username=None):
    """Render the main dashboard page"""
    return render_template('index.html', username=username)
    
@app.route('/api/auth/check-setup')
def check_setup():
    """Check if setup is needed"""
    return jsonify({
        'needsSetup': is_setup_needed()
    })

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Handle local authentication"""
    data = request.get_json() or {}
    
    username = data.get('username')
    password = data.get('password')
    
    # Check if this is a first-time setup
    if is_setup_needed():
        success, message = create_user(username, password)
        if not success:
            return jsonify({
                'success': False,
                'message': message
            }), 400
    else:
        # Regular login
        success, message = validate_credentials(username, password)
        if not success:
            return jsonify({
                'success': False,
                'message': message
            }), 401
    
    # Generate token for API access
    token, expiry = generate_token(username)
    
    response = jsonify({
        'success': True,
        'message': 'Login successful',
        'token': token,
        'expires': expiry,
        'username': username
    })
    
    # Set cookie for web interface
    response.set_cookie(
        'auth_token', 
        token,
        httponly=True,
        max_age=expiry - int(time.time()),
        path='/'
    )
    
    return response

@app.route('/api/auth/logout', methods=['POST'])
@auth_required
def auth_logout(username=None):
    """Handle logout"""
    token = request.cookies.get('auth_token')
    if token:
        revoke_token(token)
        
    response = jsonify({
        'success': True,
        'message': 'Logout successful'
    })
    
    # Clear auth cookie
    response.delete_cookie('auth_token', path='/')
    
    return response


@app.route('/api/status')
@auth_required
def status(username=None):
    """Return the current mining status, reading from GUI stubs when possible."""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503

    try:
        twitch = tdm_instance
        gui = _get_gui()

        # State
        state_name = str(twitch._state.name) if hasattr(twitch, '_state') else 'UNKNOWN'

        # Status message from GUI stub
        status_message = gui.status.message if gui else ''

        # Username
        username = None
        if hasattr(twitch, '_auth_state') and hasattr(twitch._auth_state, 'user_id'):
            user_id = twitch._auth_state.user_id
            if user_id != 0:
                username = str(user_id)

        # Channel info — prefer GUI stub data, fall back to twitch internals
        current_channel = None
        current_game = None
        current_channel_status = 'NONE'

        if gui and hasattr(gui, 'channels') and hasattr(gui.channels, 'watching'):
            watching = gui.channels.watching
            if watching is not None:
                current_channel = watching.name
                current_channel_status = 'ONLINE' if watching.online else 'OFFLINE'
                if watching.game:
                    current_game = watching.game.name
        else:
            watching_channel = twitch.watching_channel.get_with_default(None)
            if watching_channel:
                current_channel = watching_channel.name
                current_channel_status = 'ONLINE' if watching_channel.online else 'OFFLINE'
                if watching_channel.game:
                    current_game = watching_channel.game.name

        # Active drop — prefer GUI stub progress data
        current_drop = None
        drop_progress = None
        time_remaining = None

        if gui and hasattr(gui, 'progress'):
            drop = gui.progress.current_drop
            if drop is not None:
                current_drop = drop.name
                drop_progress = f"{drop.current_minutes}/{drop.required_minutes}"
                time_remaining = f"{drop.remaining_minutes} minutes"

        # Fall back to get_active_drop
        if current_drop is None:
            watching_channel = twitch.watching_channel.get_with_default(None)
            active_drop = twitch.get_active_drop(watching_channel)
            if active_drop:
                current_drop = active_drop.name
                drop_progress = f"{active_drop.current_minutes}/{active_drop.required_minutes}"
                time_remaining = f"{active_drop.remaining_minutes} minutes"

        # Count pending drops
        inventory_pending = 0
        for campaign in twitch.inventory:
            for drop in campaign.drops:
                if drop.can_claim:
                    inventory_pending += 1

        # Tray icon state
        icon_state = gui.tray.icon_state if gui else 'idle'

        current_status = {
            'state': state_name,
            'status_message': status_message,
            'username': username,
            'current_channel': current_channel,
            'current_game': current_game,
            'current_channel_status': current_channel_status,
            'current_drop': current_drop,
            'drop_progress': drop_progress,
            'time_remaining': time_remaining,
            'inventory_pending': inventory_pending,
            'icon_state': icon_state,
        }
        return jsonify(current_status)
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/campaigns')
@auth_required
def campaigns(username=None):
    """Return the available campaigns"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        campaigns_data = []
          # The inventory is a list of DropsCampaign objects in twitch.inventory
        if hasattr(twitch, 'inventory') and isinstance(twitch.inventory, list):
            for campaign in twitch.inventory:
                campaign_data = {
                    'id': campaign.id if hasattr(campaign, 'id') else 'unknown',
                    'name': campaign.name if hasattr(campaign, 'name') else 'Unknown Campaign',
                    'image_url': campaign.image_url if hasattr(campaign, 'image_url') else None,
                }
                
                # Add game info if available
                if hasattr(campaign, 'game') and campaign.game:
                    campaign_data['game'] = campaign.game.name if hasattr(campaign.game, 'name') else 'Unknown Game'
                else:
                    campaign_data['game'] = None
                    
                # Add status based on campaign properties
                if hasattr(campaign, 'active'):
                    campaign_data['status'] = 'ACTIVE' if campaign.active else 'INACTIVE'
                elif hasattr(campaign, 'upcoming') and campaign.upcoming:
                    campaign_data['status'] = 'UPCOMING'
                elif hasattr(campaign, 'expired') and campaign.expired:
                    campaign_data['status'] = 'EXPIRED'
                else:
                    campaign_data['status'] = 'UNKNOWN'
                    
                # Add time info
                campaign_data['start_time'] = campaign.starts_at.isoformat() if hasattr(campaign, 'starts_at') and campaign.starts_at else None
                campaign_data['end_time'] = campaign.ends_at.isoformat() if hasattr(campaign, 'ends_at') and campaign.ends_at else None
                  # Add drops count and progress info
                campaign_data['drops_count'] = len(campaign.drops) if hasattr(campaign, 'drops') else 0
                campaign_data['claimed_drops'] = campaign.claimed_drops if hasattr(campaign, 'claimed_drops') else 0
                campaign_data['total_drops'] = campaign.total_drops if hasattr(campaign, 'total_drops') else 0
                campaign_data['progress'] = campaign.progress if hasattr(campaign, 'progress') else 0
                
                # Add properties needed for filtering
                campaign_data['active'] = campaign.active if hasattr(campaign, 'active') else False
                campaign_data['upcoming'] = campaign.upcoming if hasattr(campaign, 'upcoming') else False
                campaign_data['expired'] = campaign.expired if hasattr(campaign, 'expired') else False
                campaign_data['linked'] = campaign.linked if hasattr(campaign, 'linked') else False
                campaign_data['eligible'] = campaign.eligible if hasattr(campaign, 'eligible') else False
                campaign_data['finished'] = campaign.finished if hasattr(campaign, 'finished') else False
                  # Check if the campaign is excluded based on settings
                campaign_data['excluded'] = False
                if hasattr(twitch, 'settings') and hasattr(campaign, 'game') and hasattr(campaign.game, 'name'):
                    if hasattr(twitch.settings, 'exclude') and campaign.game.name in twitch.settings.exclude:
                        campaign_data['excluded'] = True
                
                # Add detailed drop information for each campaign
                campaign_data['drops'] = []
                if hasattr(campaign, 'drops'):
                    for drop in campaign.drops:
                        # Get image URL from the first benefit if available
                        image_url = None
                        if hasattr(drop, 'benefits') and drop.benefits and len(drop.benefits) > 0:
                            image_url = drop.benefits[0].image_url if hasattr(drop.benefits[0], 'image_url') else None
                        
                        drop_data = {
                            'id': drop.id if hasattr(drop, 'id') else 'unknown',
                            'name': drop.name if hasattr(drop, 'name') else 'Unknown Drop',
                            'image_url': image_url,
                            'claimed': drop.claimed if hasattr(drop, 'claimed') else False,
                            'current_minutes': drop.current_minutes if hasattr(drop, 'current_minutes') else 0,
                            'required_minutes': drop.required_minutes if hasattr(drop, 'required_minutes') else 0,
                            'remaining_minutes': drop.remaining_minutes if hasattr(drop, 'remaining_minutes') else 0,
                            'progress': drop.progress if hasattr(drop, 'progress') else 0
                        }
                        campaign_data['drops'].append(drop_data)
                
                campaigns_data.append(campaign_data)
        # Fallback for older structure if inventory is not a list
        elif hasattr(twitch, 'inventory') and hasattr(twitch.inventory, 'campaigns'):
            if isinstance(twitch.inventory.campaigns, dict):
                for campaign in twitch.inventory.campaigns.values():
                    campaign_data = {
                        'id': campaign.id if hasattr(campaign, 'id') else 'unknown',
                        'name': campaign.name if hasattr(campaign, 'name') else 'Unknown Campaign',
                        'game': None,
                        'status': 'UNKNOWN',
                        'start_time': None,
                        'end_time': None,
                        'drops_count': 0,
                        'drops': []
                    }
                    campaigns_data.append(campaign_data)
            elif isinstance(twitch.inventory.campaigns, list):
                for campaign in twitch.inventory.campaigns:
                    campaign_data = {
                        'id': campaign.id if hasattr(campaign, 'id') else 'unknown',
                        'name': campaign.name if hasattr(campaign, 'name') else 'Unknown Campaign',
                        'game': None,
                        'status': 'UNKNOWN',
                        'start_time': None,
                        'end_time': None,
                        'drops_count': 0,
                        'drops': []
                    }
                    campaigns_data.append(campaign_data)
        
        return jsonify(campaigns_data)
    except Exception as e:
        logger.error(f"Error getting campaigns: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/channels')
@auth_required
def channels(username=None):
    """Return the available channels, preferring GUI stub data."""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503

    try:
        twitch = tdm_instance
        gui = _get_gui()
        channels_data = []

        # Determine currently watching channel from GUI stub
        watching_id = None
        if gui and hasattr(gui, 'channels') and hasattr(gui.channels, 'watching'):
            w = gui.channels.watching
            if w is not None:
                watching_id = w.iid
        else:
            w = twitch.watching_channel.get_with_default(None)
            if w is not None:
                watching_id = w.iid if hasattr(w, 'iid') else getattr(w, 'id', None)

        # Get channel objects — prefer GUI stub list (it mirrors what twitch.py sends)
        if gui and hasattr(gui, 'channels') and hasattr(gui.channels, 'all_channels'):
            channel_list = gui.channels.all_channels
        elif hasattr(twitch, 'channels'):
            channel_list = list(twitch.channels.values())
        else:
            channel_list = []

        for channel in channel_list:
            channel_data = {
                'id': getattr(channel, 'id', 'unknown'),
                'name': getattr(channel, 'name', 'Unknown Channel'),
                'game': channel.game.name if getattr(channel, 'game', None) else None,
                'status': 'ONLINE' if getattr(channel, 'online', False) else 'OFFLINE',
                'viewers': getattr(channel, 'viewers', 0) if getattr(channel, 'online', False) else 0,
                'has_drops': getattr(channel, 'drops_enabled', False),
                'acl_based': getattr(channel, 'acl_based', False),
                'tags': list(channel.tags) if getattr(channel, 'tags', None) else [],
                'current': (watching_id is not None and getattr(channel, 'iid', None) == watching_id),
            }
            channels_data.append(channel_data)

        return jsonify(channels_data)
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/inventory')
@auth_required
def inventory(username=None):
    """Return the inventory (claimed and pending drops)"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        inventory_data = {
            'claimed': [],
            'pending': []
        }
        
        # Process inventory if it's a list of campaigns (new structure)
        if hasattr(twitch, 'inventory') and isinstance(twitch.inventory, list):
            # Collect all claimed and pending drops from all campaigns
            for campaign in twitch.inventory:
                if not hasattr(campaign, 'drops'):
                    continue
                    
                for drop in campaign.drops:                    # Get image URL from the first benefit if available
                    image_url = None
                    if hasattr(drop, 'benefits') and drop.benefits and len(drop.benefits) > 0:
                        image_url = drop.benefits[0].image_url if hasattr(drop.benefits[0], 'image_url') else None
                    
                    drop_data = {
                        'id': drop.id if hasattr(drop, 'id') else 'unknown',
                        'name': drop.name if hasattr(drop, 'name') else 'Unknown Drop',
                        'image_url': image_url,
                    }
                    
                    # Add game info from the campaign
                    if hasattr(campaign, 'game') and campaign.game:
                        drop_data['game'] = campaign.game.name if hasattr(campaign.game, 'name') else 'Unknown Game'
                    else:
                        drop_data['game'] = None
                    
                    # Check if drop is claimed or pending
                    if hasattr(drop, 'claimed') and drop.claimed:
                        drop_data['claim_time'] = drop.claim_time.isoformat() if hasattr(drop, 'claim_time') and drop.claim_time else None
                        inventory_data['claimed'].append(drop_data)
                    else:
                        drop_data['progress'] = drop.progress if hasattr(drop, 'progress') else 0
                        drop_data['required_minutes'] = drop.required_minutes if hasattr(drop, 'required_minutes') else 0
                        drop_data['current_minutes'] = drop.current_minutes if hasattr(drop, 'current_minutes') else 0
                        inventory_data['pending'].append(drop_data)
        
        # Fallback to old structure
        else:
            # Add claimed drops
            if hasattr(twitch, 'inventory') and hasattr(twitch.inventory, 'claimed'):                
                for drop in twitch.inventory.claimed:
                    # Get image URL from the first benefit if available
                    image_url = None
                    if hasattr(drop, 'benefits') and drop.benefits and len(drop.benefits) > 0:
                        image_url = drop.benefits[0].image_url if hasattr(drop.benefits[0], 'image_url') else None
                    
                    drop_data = {
                        'id': drop.id if hasattr(drop, 'id') else 'unknown',
                        'name': drop.name if hasattr(drop, 'name') else 'Unknown Drop',
                        'image_url': image_url,
                        'claim_time': drop.claim_time.isoformat() if hasattr(drop, 'claim_time') and drop.claim_time else None,
                    }
                    
                    # Add game info if available
                    if hasattr(drop, 'campaign') and drop.campaign and hasattr(drop.campaign, 'game') and drop.campaign.game:
                        drop_data['game'] = drop.campaign.game.name if hasattr(drop.campaign.game, 'name') else 'Unknown Game'
                    else:
                        drop_data['game'] = None
                    
                    inventory_data['claimed'].append(drop_data)
                      # Add pending drops
            if hasattr(twitch, 'inventory') and hasattr(twitch.inventory, 'pending'):
                for drop in twitch.inventory.pending:
                    # Get image URL from the first benefit if available
                    image_url = None
                    if hasattr(drop, 'benefits') and drop.benefits and len(drop.benefits) > 0:
                        image_url = drop.benefits[0].image_url if hasattr(drop.benefits[0], 'image_url') else None
                    
                    drop_data = {
                        'id': drop.id if hasattr(drop, 'id') else 'unknown',
                        'name': drop.name if hasattr(drop, 'name') else 'Unknown Drop',
                        'image_url': image_url,
                        'progress': drop.current_minutes if hasattr(drop, 'current_minutes') else 0,
                        'required_minutes': drop.required_minutes if hasattr(drop, 'required_minutes') else 0,
                    }
                    
                    # Add game info if available
                    if hasattr(drop, 'campaign') and drop.campaign and hasattr(drop.campaign, 'game') and drop.campaign.game:
                        drop_data['game'] = drop.campaign.game.name if hasattr(drop.campaign.game, 'name') else 'Unknown Game'
                    else:
                        drop_data['game'] = None
                    
                    inventory_data['pending'].append(drop_data)
                    
        return jsonify(inventory_data)
    except Exception as e:
        logger.error(f"Error getting inventory: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/twitch_login', methods=['POST'])
@auth_required
def twitch_login(username=None):
    """Handle user login through the web interface"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    try:
        data = request.get_json() or {}  # Use empty dict if no data provided
        
        twitch = tdm_instance
          # Check if already logged in
        if hasattr(twitch, '_auth_state') and hasattr(twitch._auth_state, 'user_id') and twitch._auth_state.user_id != 0:
            return jsonify({
                'success': True,
                'message': 'Already logged in',
                'username': twitch.username if hasattr(twitch, 'username') else str(twitch._auth_state.user_id)
            })
            
        # Trigger login in the app
        if not hasattr(twitch, '_auth_state'):
            return jsonify({'error': 'Auth state not available'}), 500
        
        # Start OAuth device code flow
        # This is an asynchronous operation but we need to handle it synchronously in the Flask route
        # So we'll start the auth process and return the device code info to show in the UI
        
        # Get client info from the instance
        client_info = twitch._client_type
        
        # Create necessary attributes if they don't exist
        if not hasattr(twitch._auth_state, 'device_id'):
            # Generate a device ID if not exists
            twitch._auth_state.device_id = create_nonce(CHARS_HEX_LOWER, 16)
            
        # Prepare headers for OAuth request  
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Client-Id": client_info.CLIENT_ID,
            "Host": "id.twitch.tv",
            "Origin": str(client_info.CLIENT_URL),
            "Pragma": "no-cache",
            "Referer": str(client_info.CLIENT_URL),
            "User-Agent": client_info.USER_AGENT,
            "X-Device-Id": twitch._auth_state.device_id,
        }
          # Make request to get device code
        try:
            logger.info(f"Making OAuth device request with client ID: {client_info.CLIENT_ID}")
            session = requests.Session()
            response = session.post(
                "https://id.twitch.tv/oauth2/device",
                headers=headers,
                data={
                    "client_id": client_info.CLIENT_ID,
                    "scopes": ""
                }
            )
            
            if response.status_code != 200:
                error_msg = f"Failed to get device code: {response.text}"
                logger.error(error_msg)
                return jsonify({'error': error_msg}), 500
                
            logger.info("Successfully received device code from Twitch")
        except Exception as req_error:
            error_msg = f"Request to Twitch OAuth endpoint failed: {str(req_error)}"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 500
            
        # Parse response
        response_json = response.json()
        device_code = response_json["device_code"]
        user_code = response_json["user_code"]
        verification_uri = response_json["verification_uri"]
        interval = response_json["interval"]
        expires_in = response_json["expires_in"]
          # Store these values in session for later use
        session_data = {
            'device_code': device_code,
            'client_id': client_info.CLIENT_ID,
            'interval': interval,
            'expires_at': time.time() + expires_in
        }
        
        # Save this data to use in the polling endpoint
        if not hasattr(app.config, 'get'):
            # Initialize the OAUTH_SESSION if app.config doesn't have get method
            app.config.update({'OAUTH_SESSION': session_data})
        else:
            app.config['OAUTH_SESSION'] = session_data
          # Return the information needed for the frontend
        return jsonify({
            'success': True,
            'message': 'Please authorize this device on Twitch',
            'verification_uri': verification_uri,
            'user_code': user_code,
            'interval': interval,
            'expires_in': expires_in
        })
    except Exception as e:
        logger.error(f"Error during login: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/twitch_check_auth', methods=['GET'])
@auth_required
def twitch_check_auth(username=None):
    """Poll for OAuth device code authorization status"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
        
    try:
        # Check if we have an active OAuth session
        oauth_session = app.config.get('OAUTH_SESSION')
        if not oauth_session:
            return jsonify({'error': 'No active OAuth session'}), 400
            
        # Check if the session has expired
        if time.time() > oauth_session.get('expires_at', 0):
            app.config['OAUTH_SESSION'] = None
            return jsonify({'error': 'OAuth session expired', 'expired': True}), 400
            
        twitch = tdm_instance
        client_info = twitch._client_type
            
        # Prepare headers
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Client-Id": client_info.CLIENT_ID,
            "Host": "id.twitch.tv",
            "Origin": str(client_info.CLIENT_URL),
            "Pragma": "no-cache", 
            "Referer": str(client_info.CLIENT_URL),
            "User-Agent": client_info.USER_AGENT,
            "X-Device-Id": twitch._auth_state.device_id,
        }
        
        # Make request to check token status
        session = requests.Session()
        response = session.post(
            "https://id.twitch.tv/oauth2/token",
            headers=headers,
            data={
                "client_id": oauth_session['client_id'],
                "device_code": oauth_session['device_code'],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }
        )
        
        if response.status_code == 200:
            # Success - user has authorized
            response_json = response.json()
            access_token = response_json["access_token"]
            twitch._auth_state.access_token = access_token
              # The invalidate() method only removes the access token attribute but doesn't trigger validation
            # We need to manually handle cookie creation to complete the login
            try:
                # Save the auth token to cookie
                if hasattr(twitch, '_session') and twitch._session:
                    # Get the cookie jar from session
                    jar = twitch._session.cookie_jar
                    client_info = twitch._client_type
                    
                    # Create and set the auth cookie
                    cookie = {"auth-token": access_token}
                    jar.update_cookies(cookie, client_info.CLIENT_URL)
                    
                    # Set device_id if not already set
                    if hasattr(twitch._auth_state, 'device_id'):
                        cookie["unique_id"] = twitch._auth_state.device_id
                    
                    # Save cookies to disk
                    from constants import COOKIES_PATH
                    jar.save(COOKIES_PATH)
                    
                    # Mark as logged in and save the fact we're currently validating
                    if hasattr(twitch._auth_state, '_logged_in'):
                        twitch._auth_state._logged_in.set()
                        app.config['VALIDATING_AUTH'] = True
                        logger.info("Auth token saved to cookies, login event set")
                
                # Set session to None so we don't keep polling
                app.config['OAUTH_SESSION'] = None                # Instead of running validation in a separate thread with its own event loop,
                # we'll set up necessary attributes directly to complete the login process
                try:
                    if not hasattr(twitch._auth_state, 'session_id'):
                        # Generate a session ID if not exists
                        from utils import create_nonce, CHARS_HEX_LOWER
                        twitch._auth_state.session_id = create_nonce(CHARS_HEX_LOWER, 16)
                     # Get the actual user_id by validating the access token
                    access_token = twitch._auth_state.access_token
                    validation_headers = {"Authorization": f"OAuth {access_token}"}
                    validation_session = requests.Session()
                    validation_response = validation_session.get(
                        "https://id.twitch.tv/oauth2/validate",
                        headers=validation_headers
                    )

                    if validation_response.status_code == 200:
                        validation_data = validation_response.json()
                        # Set the actual user_id from the validation response
                        twitch._auth_state.user_id = int(validation_data["user_id"])
                        logger.info(f"Got actual user ID: {twitch._auth_state.user_id}")
                    else:
                        # If validation fails, log out instead of using temporary ID
                        logger.warning("Could not validate token, logging out")

                        # Clear access token
                        if hasattr(twitch._auth_state, 'access_token'):
                            delattr(twitch._auth_state, 'access_token')

                        # Reset user_id to 0
                        twitch._auth_state.user_id = 0

                        # Clear the logged_in flag
                        if hasattr(twitch._auth_state, '_logged_in'):
                            twitch._auth_state._logged_in.clear()

                        # Clear cookies related to authentication
                        if hasattr(twitch, '_session') and twitch._session is not None:
                            cookie_jar = twitch._session.cookie_jar
                            client_info = twitch._client_type
                            # Clear the auth token from cookies
                            if hasattr(client_info, 'CLIENT_URL') and client_info.CLIENT_URL.host:
                                cookie_jar.clear_domain(client_info.CLIENT_URL.host)

                            # Save the updated cookies
                            from constants import COOKIES_PATH
                            cookie_jar.save(COOKIES_PATH)

                        # Call invalidate if it exists
                        if hasattr(twitch._auth_state, 'invalidate'):
                            twitch._auth_state.invalidate()

                        # Set validation state to complete and clear OAuth session
                        app.config['VALIDATING_AUTH'] = False
                        app.config['OAUTH_SESSION'] = None

                        # Change state to IDLE if possible
                        if hasattr(twitch, 'change_state') and hasattr(State, 'IDLE'):
                            twitch.change_state(State.IDLE)
    
                    
                    # Mark as logged in
                    if hasattr(twitch._auth_state, '_logged_in'):
                        twitch._auth_state._logged_in.set()
                    
                    logger.info("Auth token saved, login event set. User now has temporary ID.")
                    
                    # Set validation state to complete
                    app.config['VALIDATING_AUTH'] = False
                    
                except Exception as e:
                    logger.error(f"Error setting up auth state: {e}")
                    app.config['VALIDATING_AUTH'] = False
                
                # Trigger a state change to force the app to reload with the new auth
                twitch.save(force=True)
            except Exception as e:
                logger.error(f"Error setting cookie during login: {e}")
            return jsonify({
                'success': True,
                'message': 'Authorization successful',
                'authorized': True
            })
        elif response.status_code == 400:
            # User hasn't entered the code yet
            return jsonify({
                'success': True,
                'message': 'Waiting for authorization',
                'authorized': False
            })
        else:
            # Some other error
            return jsonify({
                'error': f'Error checking authorization: {response.text}',
                'authorized': False
            }), 500

    except Exception as e:
        logger.error(f"Error checking auth status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/twitch_validate_auth', methods=['GET'])
@auth_required
def twitch_validate_auth(username=None):
    """Check if auth validation is complete and return user status"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
        
    try:
        twitch = tdm_instance
        
        # Check if validation is still in progress
        validating = app.config.get('VALIDATING_AUTH', False)
          # Get current username from auth_state if available
        username = None
        user_id = None
        is_logged_in = False
        
        if hasattr(twitch, '_auth_state'):
            # Check if we have a user_id
            has_user_id = hasattr(twitch._auth_state, 'user_id')
            # Check if _logged_in event exists and is set
            is_logged_in_flag = hasattr(twitch._auth_state, '_logged_in') and twitch._auth_state._logged_in.is_set()
            
            # Only set user_id if we have it
            if has_user_id:
                user_id = twitch._auth_state.user_id
                # Don't return placeholder user_id (0) to the frontend
                if user_id == 0:
                    user_id = None
                    username = None
                else:
                    username = str(user_id)  # Use user_id as username if we don't have better info            # Consider logged in if:
            # 1. The _logged_in flag is set, AND
            # 2. We have a user_id that is greater than 0
            is_logged_in = is_logged_in_flag and has_user_id and user_id is not None and user_id > 0
                
            # If the login flag is set but we don't have a proper user_id yet,
            # consider validation still in progress
            if is_logged_in_flag and (not has_user_id or user_id is None or user_id <= 0):
                validating = True
        
        return jsonify({
            'validating': validating,
            'logged_in': is_logged_in,
            'username': username,
            'user_id': user_id
        })
        
    except Exception as e:
        logger.error(f"Error checking auth validation status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/twitch_logout', methods=['POST'])
@auth_required
def twitch_logout(username=None):
    """Handle user logout through the web interface"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Check if logged in
        if not hasattr(twitch, '_auth_state') or not hasattr(twitch._auth_state, 'user_id'):
            return jsonify({
                'success': False,
                'message': 'Not logged in'
            })
        
        # Properly clear authentication state
        try:
            # Clear access token
            if hasattr(twitch._auth_state, 'access_token'):
                delattr(twitch._auth_state, 'access_token')
            
            # Clear user_id or set to 0
            if hasattr(twitch._auth_state, 'user_id'):
                twitch._auth_state.user_id = 0
            
            # Clear the logged_in flag if it exists
            if hasattr(twitch._auth_state, '_logged_in'):
                twitch._auth_state._logged_in.clear()
            
            # Clear cookies related to authentication
            if hasattr(twitch, '_session') and twitch._session is not None:
                cookie_jar = twitch._session.cookie_jar
                client_info = twitch._client_type
                twitch._auth_state.invalidate()
                # Clear the auth token from cookies
                if client_info.CLIENT_URL.host:
                    cookie_jar.clear_domain(client_info.CLIENT_URL.host)
                
                # Save the updated cookies
                from constants import COOKIES_PATH
                cookie_jar.save(COOKIES_PATH)
                
                logger.info("Auth cookies cleared during logout")
            
            # Call invalidate if it exists (for any other cleanup it might do)
            if hasattr(twitch._auth_state, 'invalidate'):
                twitch._auth_state.invalidate()
                
            # Change state to IDLE
            if hasattr(twitch, 'change_state') and hasattr(State, 'IDLE'):
                twitch.change_state(State.RELOAD)
                
            logger.info("Logout completed successfully")

            return jsonify({
                'success': True, 
                'message': 'Logout successful'
            })
        except Exception as e:
            logger.error(f"Error during logout cleanup: {e}")
            return jsonify({'error': f"Error during logout: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error during logout: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/claim/<drop_id>', methods=['POST'])
@auth_required
def claim_drop(drop_id, username=None):
    """Claim a drop with the given ID"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Check if logged in
        if not hasattr(twitch, '_auth_state') or not hasattr(twitch._auth_state, 'user_id'):
            return jsonify({
                'success': False,
                'message': 'Not logged in'
            }), 401
            
        # Find the drop with the given ID
        found_drop = None
        
        # Search in new inventory structure (list of campaigns)
        if hasattr(twitch, 'inventory') and isinstance(twitch.inventory, list):
            for campaign in twitch.inventory:
                if hasattr(campaign, 'drops'):
                    for drop in campaign.drops:
                        if hasattr(drop, 'id') and drop.id == drop_id and hasattr(drop, 'can_claim') and drop.can_claim:
                            found_drop = drop
                            break
                    if found_drop:
                        break
        # Fallback to old inventory structure
        elif hasattr(twitch, 'inventory') and hasattr(twitch.inventory, 'pending'):
            for drop in twitch.inventory.pending:
                if drop.id == drop_id:
                    found_drop = drop
                    break
        
        if not found_drop:
            return jsonify({
                'success': False,
                'message': f'No claimable drop found with ID: {drop_id}'
            }), 404
            
        # Check if drop is ready to be claimed in old structure
        if hasattr(found_drop, 'current_minutes') and hasattr(found_drop, 'required_minutes'):
            if found_drop.current_minutes < found_drop.required_minutes:
                return jsonify({
                    'success': False,
                    'message': f'Drop is not ready to be claimed: {found_drop.current_minutes}/{found_drop.required_minutes} minutes'
                }), 400
        # Or check in new structure with can_claim property
        elif hasattr(found_drop, 'can_claim') and not found_drop.can_claim:
            return jsonify({
                'success': False,
                'message': 'Drop is not ready to be claimed'
            }), 400
          # Trigger claim drop in the app
        # This will force a state change to claim the drop
        twitch.current_drop = found_drop
        if hasattr(State, 'INVENTORY_FETCH'):  # Use INVENTORY_FETCH as fallback for DROP_CLAIM
            twitch.change_state(State.INVENTORY_FETCH)
        
        return jsonify({
            'success': True, 
            'message': f'Claiming drop: {found_drop.name}'
        })
    except Exception as e:
        logger.error(f"Error claiming drop: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/set_channel/<channel_name>', methods=['POST'])
@auth_required
def set_channel(channel_name, username=None):
    """Set the active channel to the specified channel name"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Check if logged in
        if not hasattr(twitch, '_auth_state') or not hasattr(twitch._auth_state, 'user_id'):
            return jsonify({
                'success': False,
                'message': 'Not logged in'
            }), 401
            
        # Find the channel with the given name
        found_channel = None
        if hasattr(twitch, 'channels'):
            for channel in twitch.channels.values():
                if hasattr(channel, 'name') and channel.name.lower() == channel_name.lower():
                    found_channel = channel
                    break
        
        if not found_channel:
            return jsonify({
                'success': False,
                'message': f'No channel found with name: {channel_name}'
            }), 404
              # Set the channel and change state to channel watch
        twitch.current_channel = found_channel
        if hasattr(twitch, 'change_state') and hasattr(State, 'CHANNEL_SWITCH'):
            twitch.change_state(State.CHANNEL_SWITCH)
        
        return jsonify({
            'success': True, 
            'message': f'Now watching channel: {found_channel.name}'
        })
    except Exception as e:
        logger.error(f"Error setting channel: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/switch_channel', methods=['POST'])
@auth_required
def switch_channel(username=None):
    """Switch to the next channel in the list"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    try:
        twitch = tdm_instance
        
        # Check if logged in
        if not hasattr(twitch, '_auth_state') or not hasattr(twitch._auth_state, 'user_id') or twitch._auth_state.user_id == 0:
            return jsonify({
                'success': False,
                'message': 'Not logged in'
            }), 401
        
        # Change state to channel watch
        twitch.switch_channel()
        
        return jsonify({
            'success': True, 
            'message': 'Switching to the next channel'
        })
    except Exception as e:
        logger.error(f"Error switching channel: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings')
@auth_required
def settings(username=None):
    """Return the current settings"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        settings_data = {
            'proxy': str(twitch.settings.proxy) if hasattr(twitch, 'settings') else '',
            'language': twitch.settings.language if hasattr(twitch, 'settings') else '',
            'exclude': list(twitch.settings.exclude) if hasattr(twitch, 'settings') else [],
            'priority': twitch.settings.priority if hasattr(twitch, 'settings') else [],
            'autostart_tray': twitch.settings.autostart_tray if hasattr(twitch, 'settings') else False,
            'connection_quality': twitch.settings.connection_quality if hasattr(twitch, 'settings') else 1,
            'tray_notifications': twitch.settings.tray_notifications if hasattr(twitch, 'settings') else True,
            'priority_mode': twitch.settings.priority_mode.name if hasattr(twitch, 'settings') else 'PRIORITY_ONLY',
            'available_languages': [],  # TODO: expose from translate.py if needed
            'available_games': list(set(game.name for game in twitch.inventory_games())) if hasattr(twitch, 'inventory_games') else []
        }
        
        return jsonify(settings_data)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings', methods=['POST'])
@auth_required
def update_settings(username=None):
    """Update settings"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503

    try:
        twitch = tdm_instance
        data = request.json
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        if 'priority_mode' in data:
            try:
                from constants import PriorityMode
                mode = PriorityMode[data['priority_mode']]
                twitch.settings.priority_mode = mode
            except (KeyError, ValueError) as e:
                return jsonify({'error': f'Invalid priority mode: {str(e)}'}), 400
                
        if 'proxy' in data:
            from yarl import URL
            twitch.settings.proxy = URL(data['proxy'])
            
        if 'language' in data:
            twitch.settings.language = data['language']
            
        if 'autostart_tray' in data:
            twitch.settings.autostart_tray = bool(data['autostart_tray'])
            
        if 'tray_notifications' in data:
            twitch.settings.tray_notifications = bool(data['tray_notifications'])
            
        if 'connection_quality' in data:
            try:
                quality = int(data['connection_quality'])
                if 1 <= quality <= 6:
                    twitch.settings.connection_quality = quality
            except ValueError:
                pass
        
        if 'priority' in data and isinstance(data['priority'], list):
            twitch.settings.priority = data['priority']
            
        if 'exclude' in data and isinstance(data['exclude'], list):
            twitch.settings.exclude = set(data['exclude'])
        
        # Save settings to file
        twitch.settings.save()
        
        # If reload requested, trigger inventory fetch
        if data.get('reload', False):
            from constants import State
            twitch.change_state(State.INVENTORY_FETCH)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/priority', methods=['POST'])
@auth_required
def update_priority(username=None):
    """Update priority list"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
        
    try:
        twitch = tdm_instance
        data = request.json
        
        if not data or 'action' not in data:
            return jsonify({'error': 'Invalid data'}), 400
            
        action = data['action']
        
        if action == 'add' and 'game' in data:
            game_name = data['game']
            if game_name not in twitch.settings.priority:
                twitch.settings.priority.append(game_name)
                twitch.settings.save()
                
        elif action == 'remove' and 'index' in data:
            try:
                index = int(data['index'])
                if 0 <= index < len(twitch.settings.priority):
                    del twitch.settings.priority[index]
                    twitch.settings.save()
            except (ValueError, IndexError):
                return jsonify({'error': 'Invalid index'}), 400
                
        elif action == 'move' and 'index' in data and 'direction' in data:
            try:
                index = int(data['index'])
                direction = int(data['direction'])  # 1 for up, -1 for down
                
                if 0 <= index < len(twitch.settings.priority):
                    new_index = index - direction  # Subtract because up means lower index
                    
                    if 0 <= new_index < len(twitch.settings.priority):
                        item = twitch.settings.priority.pop(index)
                        twitch.settings.priority.insert(new_index, item)
                        twitch.settings.save()
            except (ValueError, IndexError):
                return jsonify({'error': 'Invalid index or direction'}), 400
        
        return jsonify({'success': True, 'priority': twitch.settings.priority})
    except Exception as e:
        logger.error(f"Error updating priority: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/exclude', methods=['POST'])
@auth_required
def update_exclude(username=None):
    """Update exclusion list"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
        
    try:
        twitch = tdm_instance
        data = request.json
        
        if not data or 'action' not in data:
            return jsonify({'error': 'Invalid data'}), 400
            
        action = data['action']
        
        if action == 'add' and 'game' in data:
            game_name = data['game']
            twitch.settings.exclude.add(game_name)
            twitch.settings.save()
                
        elif action == 'remove' and 'game' in data:
            game_name = data['game']
            if game_name in twitch.settings.exclude:
                twitch.settings.exclude.remove(game_name)
                twitch.settings.save()
        
        return jsonify({'success': True, 'exclude': list(twitch.settings.exclude)})
    except Exception as e:
        logger.error(f"Error updating exclusion list: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/diagnostic')
@auth_required
def diagnostic(username=None):
    """Return diagnostic information about the miner"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance          # System information
        system_info = {
            'version': __version__,
            'platform': sys.platform,
            'python_version': sys.version,
            'build_date': datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            'is_release': os.environ.get("RELEASE_BUILD") == "true"
        }
          # Miner state
        gui = _get_gui()
        miner_state = {
            'session_active': hasattr(twitch, '_session') and twitch._session is not None,
            'websocket_connected': False,
            'auth_valid': hasattr(twitch, '_auth_state') and hasattr(twitch._auth_state, 'user_id') and twitch._auth_state.user_id is not None,
        }

        # Prefer GUI stub websocket status
        if gui and hasattr(gui, 'websockets') and hasattr(gui.websockets, 'statuses'):
            ws_statuses = gui.websockets.statuses
            miner_state['websocket_connected'] = any(
                s.get('status') not in (None, 'Disconnected') for s in ws_statuses.values()
            )
            miner_state['websocket_details'] = [
                {'index': idx, 'status': s.get('status', 'Unknown'), 'topics': s.get('topics', 0)}
                for idx, s in ws_statuses.items()
            ]
        elif hasattr(twitch, 'websocket') and hasattr(twitch.websocket, 'websockets'):
            for ws in twitch.websocket.websockets:
                if ws.connected:
                    miner_state['websocket_connected'] = True
                    break
          # Stats
        stats = {
            'channels_count': len(twitch.channels) if hasattr(twitch, 'channels') else 0,
        }
        
        # Count campaigns and drops based on inventory structure
        if hasattr(twitch, 'inventory'):
            if isinstance(twitch.inventory, list):
                # New inventory structure (list of campaigns)
                stats['campaigns_count'] = len(twitch.inventory)
                
                # Count total drops across all campaigns
                drops_count = 0
                for campaign in twitch.inventory:
                    if hasattr(campaign, 'drops'):
                        drops_count += len(campaign.drops)
                stats['drops_count'] = drops_count
            else:
                # Old inventory structure
                stats['campaigns_count'] = len(twitch.inventory.campaigns) if hasattr(twitch.inventory, 'campaigns') else 0
                claimed_count = len(twitch.inventory.claimed) if hasattr(twitch.inventory, 'claimed') else 0
                pending_count = len(twitch.inventory.pending) if hasattr(twitch.inventory, 'pending') else 0
                stats['drops_count'] = claimed_count + pending_count
        
        return jsonify({
            'system_info': system_info,
            'miner_state': miner_state,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"Error getting diagnostic information: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/refresh_inventory', methods=['POST'])
@auth_required
def refresh_inventory(username=None):
    """Force a refresh of the inventory"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Change state to fetch inventory
        twitch.change_state(State.INVENTORY_FETCH)
        
        return jsonify({
            'success': True,
            'message': 'Inventory refresh initiated'
        })
    except Exception as e:
        logger.error(f"Error refreshing inventory: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/reload', methods=['POST'])
@auth_required
def reload(username=None):
    """Reload the miner"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Reload the miner
        twitch.reload()
        
        return jsonify({
            'success': True,
            'message': 'Miner reloaded'
        })
    except Exception as e:
        logger.error(f"Error reloading miner: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/twitch_cancel_auth', methods=['POST'])
@auth_required
def twitch_cancel_auth(username=None):
    """Handle cancellation of OAuth authentication process"""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503
    
    try:
        twitch = tdm_instance
        
        # Clear OAuth session
        app.config['OAUTH_SESSION'] = None
        
        # If auth state exists, ensure it's properly invalidated
        if hasattr(twitch, '_auth_state'):
            # Remove access_token if it exists
            if hasattr(twitch._auth_state, 'access_token'):
                twitch._auth_state.invalidate()
            else:
                # Even if there's no access_token, we still need to clear the logged_in flag
                if hasattr(twitch._auth_state, '_logged_in'):
                    twitch._auth_state._logged_in.clear()
            
            # Make sure user_id is reset to 0 if it exists
            if hasattr(twitch._auth_state, 'user_id'):
                twitch._auth_state.user_id = 0
        
        # Reset validation state if it exists
        app.config['VALIDATING_AUTH'] = False
        
        logger.info("OAuth authentication cancelled by user")
        return jsonify({
            'success': True,
            'message': 'Authentication cancelled'
        })
    except Exception as e:
        logger.error(f"Error handling auth cancellation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/active_drop')
@auth_required
def active_drop(username=None):
    """Return the currently active drop, preferring GUI stub progress data."""
    if tdm_instance is None:
        return jsonify({'error': 'Miner not initialized'}), 503

    try:
        twitch = tdm_instance
        gui = _get_gui()

        drop = None
        source = 'gql'

        # Prefer the GUI stub's tracked drop (set by progress.display())
        if gui and hasattr(gui, 'progress'):
            drop = gui.progress.current_drop
            if drop is not None:
                source = 'gui'

        # Fall back to get_active_drop
        if drop is None:
            watching_channel = twitch.watching_channel.get_with_default(None)
            drop = twitch.get_active_drop(watching_channel)

        if drop is None:
            return jsonify({'active_drop': None})

        # Get image URL from the first benefit
        image_url = None
        if getattr(drop, 'benefits', None) and len(drop.benefits) > 0:
            image_url = getattr(drop.benefits[0], 'image_url', None)

        result = {
            'source': source,
            'name': drop.name,
            'campaign_name': getattr(drop.campaign, 'name', None) if getattr(drop, 'campaign', None) else None,
            'game': drop.campaign.game.name if getattr(drop, 'campaign', None) and getattr(drop.campaign, 'game', None) else None,
            'current_minutes': drop.current_minutes,
            'required_minutes': drop.required_minutes,
            'remaining_minutes': drop.remaining_minutes,
            'progress_percentage': drop.progress_percentage if hasattr(drop, 'progress_percentage') else round(drop.progress * 100),
            'last_update': datetime.now(timezone.utc).isoformat(),
            'drop_id': getattr(drop, 'id', None),
            'image_url': image_url,
        }

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting active drop: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/validate')
def auth_validate():
    """Validate if a token is valid - no auth_required decorator as this endpoint checks token validity"""
    token = None
    if 'Authorization' in request.headers:
        auth = request.headers['Authorization']
        if auth.startswith('Bearer '):
            token = auth[7:]  # Remove 'Bearer ' prefix
    
    if not token:
        token = request.cookies.get('auth_token')
    
    if not token:
        return jsonify({
            'success': False,
            'message': 'No token provided'
        }), 401
    
    valid, username_or_error = validate_token(token)
    if not valid:
        return jsonify({
            'success': False,
            'message': username_or_error
        }), 401
    
    return jsonify({
        'success': True,
        'username': username_or_error
    })


@app.route('/api/log')
@auth_required
def get_log(username=None):
    """Return recent log messages captured by the headless GUI."""
    gui = _get_gui()
    if gui is None or not hasattr(gui, 'get_log'):
        return jsonify([])

    count = request.args.get('count', 100, type=int)
    messages = gui.get_log(last_n=count)
    return jsonify([{'timestamp': ts, 'message': msg} for ts, msg in messages])


@app.route('/api/notifications')
@auth_required
def get_notifications(username=None):
    """Return tray notifications captured by the headless GUI."""
    gui = _get_gui()
    if gui is None or not hasattr(gui, 'tray') or not hasattr(gui.tray, 'notifications'):
        return jsonify([])

    return jsonify([
        {'timestamp': ts, 'title': title, 'message': msg}
        for ts, title, msg in gui.tray.notifications
    ])


def run_web_server(host, port, debug, tdm):
    """Start the web server"""
    global tdm_instance
    tdm_instance = tdm
    app.run(host=host, port=port, debug=debug)

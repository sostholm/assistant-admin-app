import streamlit as st
import psycopg
import os
import pandas as pd
import random
import io
import hashlib
import secrets
from dotenv import load_dotenv
from ulid import ULID

# Add this at the top with other imports
try:
    from audio_recorder_streamlit import audio_recorder
    AUDIO_RECORDER_AVAILABLE = True
except ImportError:
    AUDIO_RECORDER_AVAILABLE = False
    st.warning("Audio recorder component not available. To enable direct recording, install with: pip install audio-recorder-streamlit")

# Load environment variables
load_dotenv()

DB_HOST = os.getenv('DATABASE_ADDRESS', 'localhost')
DB_PORT = os.getenv('DATABASE_PORT', '5432')
DB_NAME = os.getenv('DATABASE_NAME', 'assistant_testing')
DB_USER = os.getenv('POSTGRES_USER')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')

st.set_page_config(
    page_title="Initial Setup",
    page_icon="⚙️",
    layout="centered",
    initial_sidebar_state="auto",
)

# Initialize session state for authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0

@st.cache_resource
def get_db_connection():
    try:
        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

def check_existing_setup(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users;")
            user_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM ai;")
            ai_count = cur.fetchone()[0]

        return (user_count > 0 or ai_count > 0)
    except Exception as e:
        st.error(f"Error checking setup: {e}")
        return False

def get_or_create_microphone_device(conn, device_name):
    with conn.cursor() as cur:
        # Ensure 'Microphone' device type exists
        cur.execute("""
            INSERT INTO device_types (type_name, description)
            VALUES ('Microphone', 'A microphone device used for voice recordings')
            ON CONFLICT (type_name) DO NOTHING;
        """)
        cur.execute("SELECT id FROM device_types WHERE type_name = 'Microphone';")
        device_type_id = cur.fetchone()[0]

        # Insert the device
        cur.execute("""
            INSERT INTO devices (device_name, device_type_id, unique_identifier)
            VALUES (%s, %s, gen_random_uuid())
            RETURNING id;
        """, (device_name, device_type_id))
        device_id = cur.fetchone()[0]

        return device_id

def setup_form(conn):
    st.title("⚙️ Initial Setup")

    # FORM START
    with st.form("setup_form"):
        st.header("👤 User Information")
        full_name = st.text_input("Full Name")
        nick_name = st.text_input("Nickname")
        email = st.text_input("Email")
        phone_number = st.text_input("Phone Number")
        character_sheet = st.text_area("Character Sheet (optional)")
        life_style_preferences = st.text_area("Life Style & Preferences (optional)")

        st.header("🎙️ Device Setup")
        device_name = st.text_input("Device Name (e.g. 'Default Desktop Microphone')")

        st.header("🎤 User Voice Recognition")
        voice_file = st.file_uploader("Upload User Voice Sample (WAV/MP3)", type=["wav", "mp3"])

        st.header("🤖 AI Profile")
        ai_name = st.text_input("AI Name")
        ai_base_prompt = st.text_area("AI Base Prompt")

        st.header("🎤 AI Voice Recognition")
        ai_voice_file = st.file_uploader("Upload AI Voice Sample (WAV/MP3)", type=["wav", "mp3"])

        submit_button = st.form_submit_button(label="Complete Setup")
    # FORM END

    if submit_button:
        required_fields = [full_name, email, ai_name, ai_base_prompt, device_name]
        if any(not field for field in required_fields):
            st.error("Please fill in all required fields: Full Name, Email, AI Name, AI Base Prompt, Device Name.")
            return

        USER_ROLE_ID = 2  # Assuming 'user' role is 2.

        user_id = str(ULID())

        try:
            with conn.cursor() as cur:
                device_id = get_or_create_microphone_device(conn, device_name)

                cur.execute("""
                    INSERT INTO users (user_id, full_name, nick_name, email, phone_number, character_sheet, life_style_and_preferences, user_role_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING user_id;
                """, (user_id, full_name, nick_name, email, phone_number, character_sheet, life_style_preferences, USER_ROLE_ID))
                user_id = cur.fetchone()[0]

                if voice_file:
                    voice_bytes = voice_file.read()
                    cur.execute("""
                        INSERT INTO voice_recognition (user_id, voice_recognition, recorded_on)
                        VALUES (%s, %s, %s);
                    """, (user_id, voice_bytes, device_id))

                cur.execute("""
                    INSERT INTO ai (ai_name, ai_base_prompt)
                    VALUES (%s, %s) RETURNING ai_id;
                """, (ai_name, ai_base_prompt))
                ai_id = cur.fetchone()[0]

                if ai_voice_file:
                    ai_voice_bytes = ai_voice_file.read()
                    cur.execute("""
                        INSERT INTO voice_recognition (ai_id, voice_recognition, recorded_on)
                        VALUES (%s, %s, %s);
                    """, (ai_id, ai_voice_bytes, device_id))

            conn.commit()
            st.success("🎉 Setup completed successfully!")
            st.balloons()
            st.stop()

        except Exception as e:
            if conn and not conn.closed:
                conn.rollback()
            st.error(f"Setup failed: {e}")

def get_users(conn):
    # Fetch all users from the users table
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                u.user_id,
                u.full_name,
                u.nick_name, 
                u.email,
                u.phone_number,
                u.character_sheet,
                u.life_style_and_preferences,
                ur.role_name,
                ur.role_description,
                u.user_role_id
            FROM users u
            LEFT JOIN user_roles ur ON u.user_role_id = ur.role_id
        """)
        user_rows = cur.fetchall()
        
        # Now fetch all AI
        cur.execute("""
            SELECT 
                ai_id,
                ai_name,
                ai_base_prompt
            FROM ai
        """)
        ai_rows = cur.fetchall()
        
    # Return combined data
    return user_rows, ai_rows

def update_human_user(conn, user_id, full_name, nick_name, email, phone_number, character_sheet=None, life_style_preferences=None):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET full_name = %s, nick_name = %s, email = %s, phone_number = %s, 
                character_sheet = %s, life_style_and_preferences = %s
            WHERE user_id = %s
        """, (full_name, nick_name, email, phone_number, character_sheet, life_style_preferences, user_id))
    conn.commit()

def update_ai_user(conn, ai_id, ai_name, ai_base_prompt):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ai
            SET ai_name = %s, ai_base_prompt = %s
            WHERE ai_id = %s
        """, (ai_name, ai_base_prompt, ai_id))
    conn.commit()

def get_device_types(conn):
    """Get all device types from the database"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, type_name, description
            FROM device_types
            ORDER BY type_name
        """)
        return cur.fetchall()

def get_devices(conn):
    """Get all devices from the database with their type information"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.device_name, dt.type_name, 
                   d.unique_identifier::text, -- Cast UUID to text
                   d.ip_address, d.mac_address, d.location, d.status, 
                   d.registered_at, d.last_seen_at
            FROM devices d
            JOIN device_types dt ON d.device_type_id = dt.id
            ORDER BY d.device_name
        """)
        return cur.fetchall()

def create_device_type(conn, type_name, description):
    """Create a new device type"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_types (type_name, description)
            VALUES (%s, %s)
            ON CONFLICT (type_name) DO UPDATE
            SET description = EXCLUDED.description
            RETURNING id
        """, (type_name, description))
        device_type_id = cur.fetchone()[0]
        conn.commit()
        return device_type_id

def create_device(conn, device_name, device_type_id, location=None, ip_address=None, mac_address=None):
    """Create a new device"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO devices (device_name, device_type_id, unique_identifier, location, ip_address, mac_address)
            VALUES (%s, %s, gen_random_uuid(), %s, %s, %s)
            RETURNING id
        """, (device_name, device_type_id, location, ip_address, mac_address))
        device_id = cur.fetchone()[0]
        conn.commit()
        return device_id

def get_microphone_devices(conn):
    """Get all microphone devices from the database"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.device_name, d.location
            FROM devices d
            JOIN device_types dt ON d.device_type_id = dt.id
            WHERE dt.type_name = 'Microphone'
            ORDER BY d.device_name
        """)
        return cur.fetchall()

def save_voice_recognition(conn, user_id=None, ai_id=None, voice_data=None, device_id=None):
    """Save voice recognition data for user or AI"""
    if not voice_data or (user_id is None and ai_id is None) or not device_id:
        return False
        
    with conn.cursor() as cur:
        if user_id:
            cur.execute("""
                INSERT INTO voice_recognition (user_id, voice_recognition, recorded_on)
                VALUES (%s, %s, %s)
            """, (user_id, voice_data, device_id))
        elif ai_id:
            cur.execute("""
                INSERT INTO voice_recognition (ai_id, voice_recognition, recorded_on)
                VALUES (%s, %s, %s)
            """, (ai_id, voice_data, device_id))
        
        conn.commit()
        return True

def generate_reading_snippet():
    """Generate a random snippet of text for users to read aloud"""
    snippets = [
        "The quick brown fox jumps over the lazy dog. Packed with vitamins and minerals, orange juice is a healthy beverage. The weather forecast predicts sunny skies for the weekend.",
        "A journey of a thousand miles begins with a single step. Technology continues to evolve at a rapid pace. Remember to drink plenty of water throughout the day.",
        "Stars twinkle brightly in the night sky. The ancient oak tree provides shade on hot summer days. Books open doors to new worlds and adventures.",
        "Fresh baked bread fills the kitchen with its delicious aroma. The mountain peak was covered in pristine snow. Learning a new skill takes patience and practice.",
        "Waves crash against the rocky shore with rhythmic precision. The museum exhibit featured artifacts from ancient civilizations. Laughter is often the best medicine for stress.",
        "The orchestra performed the symphony with incredible precision. Gardens require regular maintenance to flourish throughout the seasons. The documentary explored the depths of the ocean.",
        "Digital technology has transformed how we communicate globally. The hiking trail offered spectacular views of the valley below. A balanced diet is essential for maintaining good health.",
        "The historical novel transported readers to another era. Birds begin their melodious songs at dawn each morning. The art gallery showcased works from emerging local artists."
    ]
    return random.choice(snippets)

def user_management_view(conn):
    st.title("👥 User Management")

    user_rows, ai_rows = get_users(conn)

    if not user_rows and not ai_rows:
        st.info("No users found.")
        return

    # Create tabs for Human Users, AI Users, Devices, and Voice Recognition
    user_tab, ai_tab, device_tab, voice_tab = st.tabs(["👤 Human Users", "🤖 AI Users", "🔌 Devices", "🎤 Voice Recognition"])
    
    with user_tab:
        if not user_rows:
            st.info("No human users found.")
        else:
            # Create options for human users
            user_options = []
            user_map = {}
            for u in user_rows:
                user_id, full_name, nick_name, email, phone_number, character_sheet, life_style_preferences, role_name, role_description, user_role_id = u
                display_name = f"👤 {full_name} ({role_name})"
                user_options.append(display_name)
                user_map[display_name] = u
            
            selected_user = st.selectbox("Select a human user to manage:", user_options)
            
            if selected_user:
                u = user_map[selected_user]
                user_id, full_name, nick_name, email, phone_number, character_sheet, life_style_preferences, role_name, role_description, user_role_id = u
                
                st.subheader("Edit User Details")
                
                with st.form("edit_human_form"):
                    new_full_name = st.text_input("Full Name", value=full_name or "")
                    new_nick_name = st.text_input("Nickname", value=nick_name or "")
                    new_email = st.text_input("Email", value=email or "")
                    new_phone = st.text_input("Phone Number", value=phone_number or "")
                    new_character_sheet = st.text_area("Character Sheet", value=character_sheet or "")
                    new_life_style = st.text_area("Life Style & Preferences", value=life_style_preferences or "")
                    submit_human = st.form_submit_button("Save Changes")
                
                if submit_human:
                    try:
                        update_human_user(conn, user_id, new_full_name, new_nick_name, new_email, new_phone, new_character_sheet, new_life_style)
                        st.success("Human user updated successfully!")
                    except Exception as e:
                        st.error(f"Error updating user: {e}")

    with ai_tab:
        if not ai_rows:
            st.info("No AI users found.")
        else:
            # Create options for AI users
            ai_options = []
            ai_map = {}
            for a in ai_rows:
                ai_id, ai_name, ai_base_prompt = a
                display_name = f"🤖 {ai_name}"
                ai_options.append(display_name)
                ai_map[display_name] = a
            
            selected_ai = st.selectbox("Select an AI to manage:", ai_options)
            
            if selected_ai:
                a = ai_map[selected_ai]
                ai_id, ai_name, ai_base_prompt = a
                
                st.subheader("Edit AI Details")
                
                with st.form("edit_ai_form"):
                    new_ai_name = st.text_input("AI Name", value=ai_name or "")
                    new_ai_base_prompt = st.text_area("AI Base Prompt", value=ai_base_prompt or "")
                    submit_ai = st.form_submit_button("Save Changes")
                
                if submit_ai:
                    try:
                        update_ai_user(conn, ai_id, new_ai_name, new_ai_base_prompt)
                        st.success("AI user updated successfully!")
                    except Exception as e:
                        st.error(f"Error updating AI: {e}")

    with device_tab:
        st.header("🔌 Device Management")
        
        # Create tabs for device types and devices
        device_types_tab, devices_tab = st.tabs(["Device Types", "Devices"])
        
        with device_types_tab:
            st.subheader("Device Types")
            
            # Display existing device types
            device_types = get_device_types(conn)
            if not device_types:
                st.info("No device types found.")
            else:
                device_type_df = pd.DataFrame(
                    device_types, 
                    columns=["ID", "Type Name", "Description"]
                )
                st.dataframe(device_type_df, use_container_width=True)
            
            # Form to add a new device type
            with st.form("add_device_type_form"):
                st.subheader("Add New Device Type")
                new_type_name = st.text_input("Type Name")
                new_type_description = st.text_area("Description")
                submit_type = st.form_submit_button("Add Device Type")
            
            if submit_type:
                if not new_type_name:
                    st.error("Type Name is required.")
                else:
                    try:
                        create_device_type(conn, new_type_name, new_type_description)
                        st.success(f"Device type '{new_type_name}' created successfully!")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Error creating device type: {e}")
                        
        with devices_tab:
            st.subheader("Devices")
            
            # Display existing devices
            devices = get_devices(conn)
            if not devices:
                st.info("No devices found.")
            else:
                device_df = pd.DataFrame(
                    devices,
                    columns=["ID", "Name", "Type", "UUID", "IP Address", "MAC Address", 
                             "Location", "Status", "Registered At", "Last Seen At"]
                )
                st.dataframe(device_df, use_container_width=True)
            
            # Form to add a new device
            with st.form("add_device_form"):
                st.subheader("Add New Device")
                
                # Get device types for dropdown
                device_types = get_device_types(conn)
                device_type_options = [f"{dt[0]} - {dt[1]}" for dt in device_types]
                
                new_device_name = st.text_input("Device Name")
                new_device_type = st.selectbox(
                    "Device Type", 
                    options=device_type_options if device_types else ["No device types available"]
                )
                new_device_location = st.text_input("Location (optional)")
                new_device_ip = st.text_input("IP Address (optional)")
                new_device_mac = st.text_input("MAC Address (optional)")
                
                submit_device = st.form_submit_button("Add Device")
            
            if submit_device:
                if not new_device_name:
                    st.error("Device Name is required.")
                elif "No device types available" in new_device_type:
                    st.error("Please create a device type first.")
                else:
                    try:
                        # Extract device type ID from the selection
                        device_type_id = int(new_device_type.split(" - ")[0])
                        
                        create_device(
                            conn, 
                            new_device_name, 
                            device_type_id,
                            location=new_device_location if new_device_location else None,
                            ip_address=new_device_ip if new_device_ip else None,
                            mac_address=new_device_mac if new_device_mac else None
                        )
                        
                        st.success(f"Device '{new_device_name}' created successfully!")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Error creating device: {e}")

    with voice_tab:
        st.header("🎤 Voice Recognition Registration")
        
        # Create tabs for human and AI voice registration
        human_voice_tab, ai_voice_tab = st.tabs(["Register Human Voice", "Register AI Voice"])
        
        with human_voice_tab:
            st.subheader("Register Human Voice Sample")
            
            # Select a human user
            if not user_rows:
                st.info("No human users found. Please create a user first.")
            else:
                # Create user selection dropdown
                user_options = []
                user_map = {}
                for u in user_rows:
                    user_id, full_name, nick_name, email, phone_number, character_sheet, life_style_preferences, role_name, role_description, user_role_id = u
                    display_name = f"{full_name} ({email})"
                    user_options.append(display_name)
                    user_map[display_name] = u
                
                selected_user = st.selectbox(
                    "Select User:", 
                    options=user_options,
                    key="human_voice_user"
                )
                
                # Get microphone devices
                mic_devices = get_microphone_devices(conn)
                if not mic_devices:
                    st.error("No microphone devices found. Please add a microphone device first.")
                else:
                    device_options = [f"{d[0]} - {d[1]}" + (f" ({d[2]})" if d[2] else "") for d in mic_devices]
                    device_map = {opt: d[0] for opt, d in zip(device_options, mic_devices)}
                    
                    selected_device = st.selectbox(
                        "Select Microphone Device:",
                        options=device_options,
                        key="human_voice_device"
                    )
                    
                    st.info("For best recognition results, record a sample on each microphone device you plan to use.")
                    
                    # Choose between recording and uploading based on availability
                    record_methods = ["Upload file"]
                    if AUDIO_RECORDER_AVAILABLE:
                        record_methods.insert(0, "Record directly")
                        
                    record_method = st.radio(
                        "Choose recording method:",
                        options=record_methods,
                        key="human_record_method"
                    )
                    
                    if record_method == "Record directly" and AUDIO_RECORDER_AVAILABLE:
                        # Generate text for user to read
                        if "reading_text_human" not in st.session_state:
                            st.session_state.reading_text_human = generate_reading_snippet()
                            
                        # Display the text for the user to read
                        st.subheader("Please read the following text:")
                        st.markdown(f"**{st.session_state.reading_text_human}**")
                        
                        # Record audio using the imported component
                        st.write("Click the microphone to start recording:")
                        audio_bytes = audio_recorder(
                            pause_threshold=3.0, 
                            text="Click to record",
                            recording_color="#e8b62c",
                            neutral_color="#6aa36f",
                            icon_name="microphone",
                            key="human_voice_recorder"  # Add unique key here
                        )
                        
                        # New text button
                        if st.button("Generate New Text", key="new_text_human"):
                            st.session_state.reading_text_human = generate_reading_snippet()
                            st.experimental_rerun()
                        
                        if audio_bytes:
                            st.success("Audio recorded successfully!")
                            st.audio(audio_bytes, format="audio/wav")
                            
                            if st.button("Register This Recording", key="register_human_recording"):
                                try:
                                    # Get user ID from selection
                                    selected_user_data = user_map[selected_user]
                                    user_id = selected_user_data[0]
                                    
                                    # Get device ID from selection
                                    device_id = device_map[selected_device]
                                    
                                    # Save to database
                                    if save_voice_recognition(conn, user_id=user_id, voice_data=audio_bytes, device_id=device_id):
                                        st.success(f"Voice recording registered successfully for {selected_user} on device {selected_device}")
                                    else:
                                        st.error("Failed to register voice recording.")
                                except Exception as e:
                                    st.error(f"Error registering voice recording: {e}")
                    else:  # Upload file option
                        # If direct recording selected but not available
                        if record_method == "Record directly":
                            st.error("Direct recording is not available. Please install the required package.")
                        
                        # Show the text the user should read
                        if "reading_text_human_upload" not in st.session_state:
                            st.session_state.reading_text_human_upload = generate_reading_snippet()
                            
                        st.subheader("Please read this text in your recording:")
                        st.markdown(f"**{st.session_state.reading_text_human_upload}**")
                        
                        if st.button("Generate New Text", key="new_text_human_upload"):
                            st.session_state.reading_text_human_upload = generate_reading_snippet()
                            st.experimental_rerun()
                        
                        # Upload voice sample
                        voice_file = st.file_uploader(
                            "Upload Voice Sample (WAV/MP3)", 
                            type=["wav", "mp3"],
                            key="human_voice_file"
                        )
                        
                        if st.button("Register Voice Sample", key="register_human_voice"):
                            if not voice_file:
                                st.error("Please upload a voice sample file.")
                            else:
                                try:
                                    # Get user ID from selection
                                    selected_user_data = user_map[selected_user]
                                    user_id = selected_user_data[0]
                                    
                                    # Get device ID from selection
                                    device_id = device_map[selected_device]
                                    
                                    # Read voice file data
                                    voice_data = voice_file.read()
                                    
                                    # Save to database
                                    if save_voice_recognition(conn, user_id=user_id, voice_data=voice_data, device_id=device_id):
                                        st.success(f"Voice sample registered successfully for {selected_user} on device {selected_device}")
                                    else:
                                        st.error("Failed to register voice sample.")
                                except Exception as e:
                                    st.error(f"Error registering voice sample: {e}")
        
        with ai_voice_tab:
            st.subheader("Register AI Voice Sample")
            
            # Select an AI
            if not ai_rows:
                st.info("No AIs found. Please create an AI first.")
            else:
                # Create AI selection dropdown
                ai_options = []
                ai_map = {}
                for a in ai_rows:
                    ai_id, ai_name, ai_base_prompt = a
                    display_name = f"{ai_name}"
                    ai_options.append(display_name)
                    ai_map[display_name] = a
                
                selected_ai = st.selectbox(
                    "Select AI:", 
                    options=ai_options,
                    key="ai_voice_ai"
                )
                
                # Get microphone devices
                mic_devices = get_microphone_devices(conn)
                if not mic_devices:
                    st.error("No microphone devices found. Please add a microphone device first.")
                else:
                    device_options = [f"{d[0]} - {d[1]}" + (f" ({d[2]})" if d[2] else "") for d in mic_devices]
                    device_map = {opt: d[0] for opt, d in zip(device_options, mic_devices)}
                    
                    selected_device = st.selectbox(
                        "Select Microphone Device:",
                        options=device_options,
                        key="ai_voice_device"
                    )
                    
                    st.info("Register AI voice samples for accurate voice recognition.")
                    
                    # Choose between recording and uploading based on availability
                    record_methods = ["Upload file"]
                    if AUDIO_RECORDER_AVAILABLE:
                        record_methods.insert(0, "Record directly")
                        
                    record_method = st.radio(
                        "Choose recording method:",
                        options=record_methods,
                        key="ai_record_method"
                    )
                    
                    if record_method == "Record directly" and AUDIO_RECORDER_AVAILABLE:
                        # Generate text for AI voice sample
                        if "reading_text_ai" not in st.session_state:
                            st.session_state.reading_text_ai = generate_reading_snippet()
                            
                        # Display the text
                        st.subheader("Please record the AI voice reading this text:")
                        st.markdown(f"**{st.session_state.reading_text_ai}**")
                        
                        # Record audio using the imported component
                        st.write("Click the microphone to start recording:")
                        audio_bytes = audio_recorder(
                            pause_threshold=3.0,
                            text="Click to record",
                            recording_color="#e8b62c",
                            neutral_color="#6aa36f",
                            icon_name="microphone",
                            key="ai_voice_recorder"  # Add unique key here
                        )
                        
                        # New text button
                        if st.button("Generate New Text", key="new_text_ai"):
                            st.session_state.reading_text_ai = generate_reading_snippet()
                            st.experimental_rerun()
                        
                        if audio_bytes:
                            st.success("Audio recorded successfully!")
                            st.audio(audio_bytes, format="audio/wav")
                            
                            if st.button("Register This Recording", key="register_ai_recording"):
                                try:
                                    # Get AI ID from selection
                                    selected_ai_data = ai_map[selected_ai]
                                    ai_id = selected_ai_data[0]
                                    
                                    # Get device ID from selection
                                    device_id = device_map[selected_device]
                                    
                                    # Save to database
                                    if save_voice_recognition(conn, ai_id=ai_id, voice_data=audio_bytes, device_id=device_id):
                                        st.success(f"Voice recording registered successfully for {selected_ai} on device {selected_device}")
                                    else:
                                        st.error("Failed to register voice recording.")
                                except Exception as e:
                                    st.error(f"Error registering voice recording: {e}")
                    else:  # Upload file option
                        # If direct recording selected but not available
                        if record_method == "Record directly":
                            st.error("Direct recording is not available. Please install the required package.")
                            
                        # Show the text the AI should say
                        if "reading_text_ai_upload" not in st.session_state:
                            st.session_state.reading_text_ai_upload = generate_reading_snippet()
                            
                        st.subheader("Please have the AI read this text in your recording:")
                        st.markdown(f"**{st.session_state.reading_text_ai_upload}**")
                        
                        if st.button("Generate New Text", key="new_text_ai_upload"):
                            st.session_state.reading_text_ai_upload = generate_reading_snippet()
                            st.experimental_rerun()
                        
                        # Upload voice sample
                        voice_file = st.file_uploader(
                            "Upload Voice Sample (WAV/MP3)", 
                            type=["wav", "mp3"],
                            key="ai_voice_file"
                        )
                        
                        if st.button("Register Voice Sample", key="register_ai_voice"):
                            if not voice_file:
                                st.error("Please upload a voice sample file.")
                            else:
                                try:
                                    # Get AI ID from selection
                                    selected_ai_data = ai_map[selected_ai]
                                    ai_id = selected_ai_data[0]
                                    
                                    # Get device ID from selection
                                    device_id = device_map[selected_device]
                                    
                                    # Read voice file data
                                    voice_data = voice_file.read()
                                    
                                    # Save to database
                                    if save_voice_recognition(conn, ai_id=ai_id, voice_data=voice_data, device_id=device_id):
                                        st.success(f"Voice sample registered successfully for {selected_ai} on device {selected_device}")
                                    else:
                                        st.error("Failed to register voice sample.")
                                except Exception as e:
                                    st.error(f"Error registering voice sample: {e}")

def initialize_auth_table(conn):
    """Create admin_users table if it doesn't exist"""
    try:
        with conn.cursor() as cur:
            # Create admin_users table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    salt VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error initializing auth table: {e}")
        return False

def create_default_admin(conn):
    """Create a default admin user if no admin users exist"""
    try:
        with conn.cursor() as cur:
            # Check if any admin users exist
            cur.execute("SELECT COUNT(*) FROM admin_users;")
            count = cur.fetchone()[0]
            
            if count == 0:
                # Create a default admin user
                username = "admin"
                password = "admin"  # This should be changed immediately
                salt = secrets.token_hex(16)
                password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
                
                cur.execute("""
                    INSERT INTO admin_users (username, password_hash, salt)
                    VALUES (%s, %s, %s);
                """, (username, password_hash, salt))
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Error creating default admin: {e}")
    return False

def verify_password(conn, username, password):
    """Verify if the username/password combination is valid"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT password_hash, salt, is_active
                FROM admin_users
                WHERE username = %s;
            """, (username,))
            
            result = cur.fetchone()
            if result:
                stored_hash, salt, is_active = result
                
                if not is_active:
                    return False
                    
                # Hash the provided password with the stored salt
                computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
                
                # Compare the hashes
                return computed_hash == stored_hash
    except Exception as e:
        st.error(f"Error verifying password: {e}")
    return False

def login_form():
    """Display login form and handle authentication"""
    st.title("Login to Admin Panel")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
    if submit:
        if not username or not password:
            st.error("Please enter both username and password.")
            return False
        
        conn = get_db_connection()
        if not conn:
            st.error("Database connection failed.")
            return False
        
        if verify_password(conn, username, password):
            st.session_state.authenticated = True
            st.session_state.username = username
            st.success("Login successful!")
            return True
        else:
            st.session_state.login_attempts += 1
            st.error(f"Invalid username or password. Attempt {st.session_state.login_attempts} of 5.")
            
            # Lock out after too many attempts
            if st.session_state.login_attempts >= 5:
                st.error("Too many failed login attempts. Please try again later.")
                st.stop()
                
            return False
    
    return False

def logout():
    """Log out the user"""
    st.session_state.authenticated = False
    if "username" in st.session_state:
        del st.session_state.username
    st.session_state.login_attempts = 0
    st.success("Logged out successfully!")

def change_password_form(conn):
    """Allow users to change their password"""
    st.subheader("Change Password")
    
    with st.form("change_password_form"):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        submit = st.form_submit_button("Change Password")
    
    if submit:
        if not current_password or not new_password or not confirm_password:
            st.error("Please fill in all fields.")
            return
            
        if new_password != confirm_password:
            st.error("New passwords don't match.")
            return
            
        username = st.session_state.username
        
        # Verify current password
        if not verify_password(conn, username, current_password):
            st.error("Current password is incorrect.")
            return
            
        try:
            # Update password
            salt = secrets.token_hex(16)
            password_hash = hashlib.sha256((new_password + salt).encode()).hexdigest()
            
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE admin_users
                    SET password_hash = %s, salt = %s
                    WHERE username = %s;
                """, (password_hash, salt, username))
            conn.commit()
            st.success("Password changed successfully!")
        except Exception as e:
            st.error(f"Error changing password: {e}")

def main():
    conn = get_db_connection()
    if not conn:
        st.stop()
        
    # Initialize authentication table
    initialize_auth_table(conn)
    create_default_admin(conn)
    
    # Check if user is authenticated
    if not st.session_state.authenticated:
        login_form()
        st.stop()
    
    # Display logout button in sidebar
    with st.sidebar:
        st.write(f"Logged in as: {st.session_state.username}")
        if st.button("Logout"):
            logout()
            st.experimental_rerun()
        
        st.divider()
        change_password_form(conn)
    
    # Proceed with the original application
    if check_existing_setup(conn):
        # Setup completed, show user management view
        user_management_view(conn)
    else:
        # Show setup form
        setup_form(conn)

if __name__ == "__main__":
    main()

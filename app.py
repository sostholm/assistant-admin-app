# setup_app.py

import streamlit as st
import psycopg
import os
from dotenv import load_dotenv
from ulid import ULID

# Load environment variables
load_dotenv()

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'assistant_testing')
DB_USER = os.getenv('POSTGRES_USER')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')

st.set_page_config(
    page_title="Initial Setup",
    page_icon="⚙️",
    layout="centered",
    initial_sidebar_state="auto",
)

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

        USER_ROLE_ID = 2       # Assuming 'user' role is 2.

        user_id = str(ULID())

        try:
            with conn.cursor() as cur:
                device_id = get_or_create_microphone_device(conn, device_name)

                cur.execute("""
                    INSERT INTO user_profile (full_name, nick_name, email, phone_number, user_role_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING user_profile_id;
                """, (full_name, nick_name, email, phone_number, USER_ROLE_ID))
                user_profile_id = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO users (user_id, user_profile_id)
                    VALUES (%s, %s);
                """, (user_id, user_profile_id))

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
    # Fetch all users and their info
    # We join with user_types and user_profile or ai to get identifying info.
    with conn.cursor() as cur:
        # Users can be human or ai. If human, we have user_profile_id. If ai, we have ai_profile_id.
        # We'll left join both and determine which is not null.
        # user_type_id: 1=human, 2=ai (adjust if needed).
        cur.execute("""
            SELECT 
                u.user_id,
                up.full_name,
                up.nick_name,
                up.email,
                up.phone_number,
                a.ai_name,
                a.ai_base_prompt,
                u.user_type_id,
                up.user_profile_id,
                a.ai_id
            FROM users u
            LEFT JOIN user_profile up ON u.user_profile_id = up.user_profile_id
            LEFT JOIN ai a ON u.ai_profile_id = a.ai_id
        """)
        rows = cur.fetchall()

    # Each row: user_id, user_type_name, full_name, nick_name, email, phone_number, ai_name, ai_base_prompt, user_type_id, user_profile_id, ai_id
    return rows

def update_human_user(conn, user_profile_id, full_name, nick_name, email, phone_number):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE user_profile
            SET full_name = %s, nick_name = %s, email = %s, phone_number = %s
            WHERE user_profile_id = %s
        """, (full_name, nick_name, email, phone_number, user_profile_id))
    conn.commit()

def update_ai_user(conn, ai_id, ai_name, ai_base_prompt):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ai
            SET ai_name = %s, ai_base_prompt = %s
            WHERE ai_id = %s
        """, (ai_name, ai_base_prompt, ai_id))
    conn.commit()

def user_management_view(conn):
    st.title("👥 User Management")

    users = get_users(conn)

    if not users:
        st.info("No users found.")
        return

    # Distinguish by emoji
    # Assume: human=1 -> "👤", ai=2 -> "🤖"
    user_type_emojis = { "human": "👤", "ai": "🤖", "tool": "🔧" }

    # Create a mapping for display
    user_options = []
    user_map = {}
    for u in users:
        user_id, user_type_name, full_name, nick_name, email, phone_number, ai_name, ai_base_prompt, user_type_id, user_profile_id, ai_id = u
        emoji = user_type_emojis.get(user_type_name, "❓")
        display_name = f"{emoji} {full_name if full_name else ai_name} ({user_type_name})"
        user_options.append(display_name)
        user_map[display_name] = u

    selected_user = st.selectbox("Select a user to manage:", user_options)

    if selected_user:
        u = user_map[selected_user]
        user_id, user_type_name, full_name, nick_name, email, phone_number, ai_name, ai_base_prompt, user_type_id, user_profile_id, ai_id = u
        
        st.subheader("Edit User Details")

        # If human
        if user_type_name == 'human':
            with st.form("edit_human_form"):
                new_full_name = st.text_input("Full Name", value=full_name or "")
                new_nick_name = st.text_input("Nickname", value=nick_name or "")
                new_email = st.text_input("Email", value=email or "")
                new_phone = st.text_input("Phone Number", value=phone_number or "")
                submit_human = st.form_submit_button("Save Changes")

            if submit_human:
                try:
                    update_human_user(conn, user_profile_id, new_full_name, new_nick_name, new_email, new_phone)
                    st.success("Human user updated successfully!")
                except Exception as e:
                    st.error(f"Error updating user: {e}")

        # If ai
        elif user_type_name == 'ai':
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

        else:
            st.write("This user type is not supported for editing.")

def main():
    conn = get_db_connection()
    if not conn:
        st.stop()

    if check_existing_setup(conn):
        # Setup completed, show user management view
        user_management_view(conn)
    else:
        # Show setup form
        setup_form(conn)

if __name__ == "__main__":
    main()

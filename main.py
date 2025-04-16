import os
import random
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "lottery-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///lottery.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Lottery configuration
REGISTRATION_TIME = 60  # 1 minute in seconds
EXTENSION_TIME = 30  # 30 seconds
MIN_PARTICIPANTS = 5
SAVE_INTERVAL = 5  # Save progress every 5 seconds
LOG_FILE = "lottery_log.txt"

# Global lottery state
lottery_state = {
    "active": False,
    "end_time": None,
    "participants": set(),
    "winner": None,
    "extended": False,
    "status": "idle"  # idle, registration, extended, completed
}

# Database model
class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    registration_time = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f'<Participant {self.username}>'

# Create database tables
with app.app_context():
    db.create_all()

def log_message(message):
    """Write message to the log file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    
    with open(LOG_FILE, "a") as file:
        file.write(log_entry)
    
    print(message)

def save_progress():
    """Save the current progress to the log file"""
    if lottery_state["participants"]:
        participants_str = ", ".join(lottery_state["participants"])
        log_message(f"Progress saved. Current participants: {participants_str}")
    else:
        log_message(f"Progress saved. No participants yet.")

def select_winner():
    """Select a random winner from the participants"""
    if not lottery_state["participants"]:
        log_message("No participants registered. No winner to select.")
        return None
    
    winner = random.choice(list(lottery_state["participants"]))
    log_message(f"Winner selected: {winner}")
    return winner

def format_participants_list():
    """Format the list of participants for the log file"""
    if not lottery_state["participants"]:
        return "No participants registered."
    
    return "Participants:\n" + "\n".join([f"- {name}" for name in sorted(lottery_state["participants"])])

def lottery_timer():
    """Background thread function to manage lottery timing"""
    start_time = time.time()
    lottery_state["end_time"] = start_time + REGISTRATION_TIME
    lottery_state["status"] = "registration"
    lottery_state["active"] = True
    
    # Initialize log file
    with open(LOG_FILE, "w") as file:
        file.write(f"Lottery Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write("=" * 50 + "\n")
    
    log_message(f"Registration period started. Duration: {REGISTRATION_TIME} seconds")
    
    last_save_time = time.time()
    
    # Main lottery timing loop
    while lottery_state["active"] and time.time() < lottery_state["end_time"]:
        # Check if we need to save progress
        if time.time() - last_save_time >= SAVE_INTERVAL:
            save_progress()
            last_save_time = time.time()
        
        time.sleep(1)
    
    # Check if registration period ended naturally (not interrupted)
    if time.time() >= lottery_state["end_time"]:
        # Check if extension is needed
        if len(lottery_state["participants"]) < MIN_PARTICIPANTS and len(lottery_state["participants"]) > 0 and not lottery_state["extended"]:
            log_message(f"Less than {MIN_PARTICIPANTS} participants registered. Extending registration period by {EXTENSION_TIME} seconds.")
            lottery_state["end_time"] = time.time() + EXTENSION_TIME
            lottery_state["extended"] = True
            lottery_state["status"] = "extended"
            
            # Continue timing for extension period
            while lottery_state["active"] and time.time() < lottery_state["end_time"]:
                if time.time() - last_save_time >= SAVE_INTERVAL:
                    save_progress()
                    last_save_time = time.time()
                
                time.sleep(1)
    
    # Finalize lottery
    lottery_state["active"] = False
    lottery_state["status"] = "completed"
    log_message("Registration period closed")
    
    # Log all participants
    participant_list = format_participants_list()
    log_message(participant_list)
    
    # Check if we have participants
    if not lottery_state["participants"]:
        log_message("No participants registered. The lottery has been cancelled.")
        return
    
    # Select and announce the winner
    lottery_state["winner"] = select_winner()
    
    # Final log entry
    log_message(f"Lottery completed. Total participants: {len(lottery_state['participants'])}. Winner: {lottery_state['winner']}")
    
    # Write a summary to the log file
    with open(LOG_FILE, "a") as file:
        file.write("\n" + "=" * 50 + "\n")
        file.write("LOTTERY SUMMARY\n")
        file.write(f"Start time: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"Total participants: {len(lottery_state['participants'])}\n")
        file.write(f"Winner: {lottery_state['winner']}\n")
        file.write("=" * 50 + "\n")

def validate_username(username):
    """Validate the username input"""
    if not username or username.isspace():
        return False, "Username cannot be empty"
    
    if username in lottery_state["participants"]:
        return False, "Username already exists"
    
    # Basic validation - only allow alphanumeric and underscores
    if not all(c.isalnum() or c == '_' for c in username):
        return False, "Username can only contain letters, numbers, and underscores"
    
    return True, "Valid username"

@app.route('/')
def index():
    remaining_seconds = 0
    if lottery_state["active"] and lottery_state["end_time"]:
        remaining_seconds = max(0, int(lottery_state["end_time"] - time.time()))
    
    return render_template('index.html', 
                          lottery_state=lottery_state, 
                          participants=sorted(lottery_state["participants"]), 
                          remaining_seconds=remaining_seconds)

@app.route('/start_lottery', methods=['POST'])
def start_lottery():
    if lottery_state["active"]:
        flash('Lottery is already in progress!', 'warning')
        return redirect(url_for('index'))
    
    # Reset lottery state
    lottery_state["participants"] = set()
    lottery_state["winner"] = None
    lottery_state["extended"] = False
    lottery_state["active"] = True
    
    # Clear existing participants from database
    with app.app_context():
        Participant.query.delete()
        db.session.commit()
    
    # Start lottery timer in background thread
    lottery_thread = threading.Thread(target=lottery_timer)
    lottery_thread.daemon = True
    lottery_thread.start()
    
    flash('Lottery registration has started!', 'success')
    return redirect(url_for('index'))

@app.route('/register', methods=['POST'])
def register():
    if not lottery_state["active"]:
        flash('Registration is not active!', 'danger')
        return redirect(url_for('index'))
    
    username = request.form.get('username', '').strip()
    
    is_valid, message = validate_username(username)
    if is_valid:
        lottery_state["participants"].add(username)
        
        # Save to database
        participant = Participant(username=username)
        db.session.add(participant)
        db.session.commit()
        
        log_message(f"User '{username}' registered. Total participants: {len(lottery_state['participants'])}")
        flash(f'Registration successful! Welcome, {username}!', 'success')
    else:
        flash(f'Registration failed: {message}', 'danger')
    
    return redirect(url_for('index'))

@app.route('/status')
def status():
    """API endpoint to get current lottery status"""
    remaining_seconds = 0
    if lottery_state["active"] and lottery_state["end_time"]:
        remaining_seconds = max(0, int(lottery_state["end_time"] - time.time()))
    
    return jsonify({
        'active': lottery_state["active"],
        'status': lottery_state["status"],
        'participants_count': len(lottery_state["participants"]),
        'remaining_seconds': remaining_seconds,
        'winner': lottery_state["winner"]
    })

if __name__ == '__main__':
    # Make sure the log directory exists
    if not os.path.exists(os.path.dirname(LOG_FILE)):
        os.makedirs(os.path.dirname(LOG_FILE))
    
    app.run(host='0.0.0.0', port=5000, debug=True)
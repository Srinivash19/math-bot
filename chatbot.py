# chatbot.py (Production-Ready - Fully Debugged and Working with Speech Toggle)
import tkinter as tk
from tkinter import scrolledtext, messagebox, font as tkFont
import threading
import logging
import configparser
from ttkthemes import ThemedTk
import speech_recognition as sr
import pyttsx3
# import faiss  # Uncomment if using FAISS for RAG or vector search
# import numpy as np # Uncomment if using numpy with FAISS or other numerical tasks
from flask import Flask, render_template, request, jsonify
import requests
import queue # Though not directly used by Tkinter UI for receiving, kept for Flask/future
import json
import time

# Configure Logging
logging.basicConfig(filename='chatbot.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration File Handling
config = configparser.ConfigParser()
if not config.read('config.ini'):
    logging.warning("config.ini not found. Using default fallback values.")
    # Create a default config object if file not found
    config['LLM'] = {
        'endpoint': "http://127.0.0.1:1234/v1/chat/completions",
        'model_name': "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF", # A common default
        'api_key': "lm-studio", # Default for LM Studio
        'temperature': '1',
        'max_tokens': '4096'
    }
    config['TTS'] = {
        'enabled_by_default': 'true',
        'voice_preference': 'male', # 'male', 'female', or part of a voice name
        'rate': '160'
    }
    with open('config.ini', 'w') as configfile: # Create a default config.ini
        config.write(configfile)
    logging.info("Created a default config.ini with LLM and TTS settings.")


LLM_ENDPOINT = config.get('LLM', 'endpoint', fallback="http://127.0.0.1:1234/v1/chat/completions")
MODEL_NAME = config.get('LLM', 'model_name', fallback="lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF")
API_KEY = config.get('LLM', 'api_key', fallback="lm-studio")
TEMPERATURE = config.getfloat('LLM', 'temperature', fallback=0.7)
MAX_TOKENS = config.getint('LLM', 'max_tokens', fallback=2048)

TTS_ENABLED_DEFAULT = config.getboolean('TTS', 'enabled_by_default', fallback=True)
TTS_VOICE_PREF = config.get('TTS', 'voice_preference', fallback='male').lower()
TTS_RATE = config.getint('TTS', 'rate', fallback=160)


# Flask App Setup
app = Flask(__name__)

# Global Queue for Thread-Safe Communication (primarily for Flask or other integrations)
response_queue = queue.Queue()

# -----------------------------------------------------------------------------
# LLM Interaction Function
# -----------------------------------------------------------------------------
def get_llm_response(conversation_history, temperature, max_tokens):
    logging.debug("Sending conversation history to LLM...")
    messages_payload = conversation_history 

    logging.debug("Payload sent to LLM: %s", json.dumps(messages_payload, indent=2))

    headers = {
        "Content-Type": "application/json",
    }
    if API_KEY and API_KEY != "None" and API_KEY != "": 
        headers["Authorization"] = f"Bearer {API_KEY}"

    data = {
        "model": MODEL_NAME,
        "messages": messages_payload,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    try:
        response = requests.post(LLM_ENDPOINT, headers=headers, data=json.dumps(data), timeout=150) 
        response.raise_for_status()
        json_response = response.json()
        logging.debug("LLM Response JSON: %s", json.dumps(json_response, indent=2))
        
        if "choices" in json_response and len(json_response["choices"]) > 0:
            if "message" in json_response["choices"][0] and "content" in json_response["choices"][0]["message"]:
                 return json_response["choices"][0]["message"]["content"].strip()
            elif "text" in json_response["choices"][0]: 
                 return json_response["choices"][0]["text"].strip()
        
        if "data" in json_response and len(json_response["data"]) > 0 and "content" in json_response["data"][0]:
            return json_response["data"][0]["content"].strip()

        logging.error(f"Unexpected LLM response structure: {json_response}")
        return "Error: Could not parse LLM response."

    except requests.exceptions.RequestException as e:
        logging.error(f"Error communicating with LLM: {e}")
        return f"Network Error: {e}"
    except (KeyError, IndexError, TypeError) as e:
        logging.error(f"Error parsing LLM response: {e}. Response: {json_response if 'json_response' in locals() else 'N/A'}")
        return f"Parsing Error: {e}"
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from LLM: {e}. Response text: {response.text if 'response' in locals() else 'N/A'}")
        return f"JSON Decode Error: {e}"


# -----------------------------------------------------------------------------
# Chatbot GUI Class
# -----------------------------------------------------------------------------
class ChatbotGUI:
    def __init__(self, master):
        self.master = master
        master.title("NovaChat Terminal v1.8") # Version bump

        self.conversation_history = [{"role": "system", "content": "You are Nova, a helpful AI assistant operating within the NovaChat Terminal. Be concise and slightly futuristic in your responses."}]
        self.bg_color = "#1E1E1E"
        self.text_area_bg = "#2D2D2D"
        self.text_color = "#76D7C4"
        self.input_bg_color = "#252525"
        self.button_color = "#007ACC"
        self.button_text_color = "#FFFFFF"
        self.accent_color = "#FF8C00"
        self.placeholder_color = "#6A6A6A"

        master.configure(bg=self.bg_color)
        try:
            self.base_font = tkFont.Font(family="Consolas", size=11)
            self.bold_font = tkFont.Font(family="Consolas", size=12, weight="bold")
        except tk.TclError: 
            self.base_font = tkFont.Font(size=10)
            self.bold_font = tkFont.Font(size=11, weight="bold")

        self.chat_log = scrolledtext.ScrolledText(master, wrap=tk.WORD, state=tk.DISABLED,
                                                  bg=self.text_area_bg, fg=self.text_color,
                                                  font=self.base_font, relief=tk.FLAT, borderwidth=2)
        self.chat_log.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        self.status_label = tk.Label(master, text="", bg=self.bg_color, fg=self.accent_color, font=self.bold_font)
        self.status_label.pack(padx=10, pady=(0, 5), fill=tk.X)
        
        input_frame = tk.Frame(master, bg=self.bg_color)
        input_frame.pack(padx=10, pady=(0,10), fill=tk.X)

        self.input_field = tk.Entry(input_frame, bg=self.input_bg_color, fg=self.placeholder_color,
                                    font=self.base_font, relief=tk.FLAT, insertbackground=self.text_color,
                                    disabledbackground=self.text_area_bg)
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self.placeholder_text = "Enter the input text here (or type 'exit_nova' to close)"
        self.input_field.config(insertwidth=2, insertontime=1000, selectbackground=self.accent_color)
        self.input_field.insert(0, self.placeholder_text)
        self.input_field.bind("<Return>", lambda event: self.handle_text_input_action())
        self.input_field.bind("<FocusIn>", self.on_entry_focus_in)
        self.input_field.bind("<FocusOut>", self.on_entry_focus_out)

        button_frame = tk.Frame(master, bg=self.bg_color)
        button_frame.pack(padx=10, pady=(0,10), fill=tk.X)
        
        self.action_button = tk.Button(button_frame, text="Generate output", command=self.handle_text_input_action,
                                       bg=self.button_color, fg=self.button_text_color, font=self.bold_font,
                                       relief=tk.FLAT, activebackground="#005C99", activeforeground=self.button_text_color,
                                       disabledforeground="#AAAAAA")
        self.action_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        
        self.voice_button = tk.Button(button_frame, text="Voice input", command=self.handle_voice_input_action,
                                      bg=self.button_color, fg=self.button_text_color, font=self.bold_font,
                                      relief=tk.FLAT, activebackground="#005C99", activeforeground=self.button_text_color,
                                      disabledforeground="#AAAAAA")
        self.voice_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2,2))

        # Speech Synthesis Toggle Button
        self.speech_synthesis_enabled = TTS_ENABLED_DEFAULT
        self.speech_toggle_button = tk.Button(button_frame, text=f"Speech: {'ON' if self.speech_synthesis_enabled else 'OFF'}", 
                                              command=self.toggle_speech_synthesis,
                                              bg=self.button_color, fg=self.button_text_color, font=self.bold_font,
                                              relief=tk.FLAT, activebackground="#005C99", activeforeground=self.button_text_color,
                                              disabledforeground="#AAAAAA")
        self.speech_toggle_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2,0))

        try:
            self.recognizer = sr.Recognizer()
            self.engine = pyttsx3.init()
            if self.engine is None: 
                 raise RuntimeError("pyttsx3 engine could not be initialized.")
            
            voices = self.engine.getProperty('voices')
            selected_voice = None
            for voice in voices: # Prioritize user preference from config
                if TTS_VOICE_PREF in voice.name.lower():
                    selected_voice = voice.id
                    break
            if not selected_voice: # Fallback logic from original code
                for voice in voices:
                    if "male" in voice.name.lower() or "david" in voice.name.lower() or "zira" not in voice.name.lower() : 
                        selected_voice = voice.id
                        break
            if selected_voice:
                 self.engine.setProperty('voice', selected_voice)
            
            self.engine.setProperty('rate', TTS_RATE) 
        except Exception as e:
            logging.error(f"Failed to initialize speech components: {e}")
            self.recognizer = None
            self.engine = None
            self.voice_button.config(state=tk.DISABLED, text="Vocal Comms (N/A)")
            self.speech_toggle_button.config(state=tk.DISABLED, text="Speech (N/A)") # Disable toggle too
            messagebox.showwarning("Speech Init Error", f"Could not initialize speech services: {e}\nVoice input and output will be disabled.")
        
        if not self.engine: # Double check if engine init failed and disable toggle button
             self.speech_toggle_button.config(state=tk.DISABLED, text="Speech (N/A)")

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.display_message("Nova: Greetings Operator. NovaChat Terminal online. How may I assist you?", sender="Nova", speak=self.speech_synthesis_enabled)

    def toggle_speech_synthesis(self):
        self.speech_synthesis_enabled = not self.speech_synthesis_enabled
        if self.speech_synthesis_enabled:
            self.speech_toggle_button.config(text="Speech: ON")
            logging.info("Speech synthesis enabled by user.")
            # Optionally, say "Speech enabled"
            # if self.engine:
            #     self.engine.say("Speech enabled")
            #     self.engine.runAndWait()
        else:
            self.speech_toggle_button.config(text="Speech: OFF")
            logging.info("Speech synthesis disabled by user.")
            if self.engine:
                self.engine.stop() # Stop any ongoing speech
            # Optionally, say "Speech disabled" using a temporary say then stop or direct system sound
            # This is tricky as self.engine.say itself would be blocked by the toggle.
            # For simplicity, no audio feedback on toggle OFF if speech was ON.

    def on_entry_focus_in(self, event):
        if self.input_field.cget('fg') == self.placeholder_color:
            self.input_field.delete(0, tk.END)
            self.input_field.config(fg=self.text_color)

    def on_entry_focus_out(self, event):
        if not self.input_field.get():
            self.input_field.insert(0, self.placeholder_text)
            self.input_field.config(fg=self.placeholder_color)

    def handle_text_input_action(self):
        user_input = self.input_field.get()
        if self.input_field.cget('fg') == self.placeholder_color or not user_input.strip():
            self.status_label.config(text="Input Array Empty. Please type a message.")
            return

        if user_input.lower() == "exit_nova":
            self.on_closing()
            return

        self.display_message(user_input, sender="Operator", speak=False) # User input is not spoken
        self.conversation_history.append({"role": "user", "content": user_input})
        
        self.input_field.delete(0, tk.END)
        self.on_entry_focus_out(None) # Reset placeholder if field is empty

        self._trigger_llm_response_generation()

    def handle_voice_input_action(self):
        if not self.recognizer:
            self.status_label.config(text="Input Offline.")
            return

        self.status_label.config(text="Receiving Input (Speak Now)...")
        self.master.update_idletasks() 
        
        user_input = self._get_voice_input()
        
        if not user_input: # Handles empty string from _get_voice_input
            self.status_label.config(text="Input Unclear or Cancelled.")
            return

        self.display_message(user_input, sender="Operator (Vocal)", speak=False) # User input is not spoken
        self.conversation_history.append({"role": "user", "content": user_input})
        self.status_label.config(text="NovaCore Processing Input...")
        self._trigger_llm_response_generation()

    def _get_voice_input(self):
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                self.status_label.config(text="Listening intently...")
                self.master.update_idletasks()
                try:
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                except sr.WaitTimeoutError:
                    self.status_label.config(text="No speech detected in time.")
                    logging.warning("Voice input: No speech detected.")
                    return "" # Return empty string for no speech
            
            self.status_label.config(text="Decoding Input...")
            self.master.update_idletasks()
            user_input = self.recognizer.recognize_google(audio)
            logging.info(f"Voice input recognized: {user_input}")
            return user_input
        except sr.UnknownValueError:
            logging.warning("Google Speech Recognition could not understand audio")
            self.status_label.config(text="Input Garbled. Try Again.")
            return ""
        except sr.RequestError as e:
            logging.error(f"Could not request results from Google Speech Recognition service; {e}")
            self.status_label.config(text="Comms Relay Error (Google Speech).")
            return ""
        except Exception as e: # Catch other potential microphone/recognition errors
            logging.error(f"Error during voice input: {e}")
            self.status_label.config(text="Input System Error.")
            messagebox.showerror("Input Error", f"An error occurred during voice input: {e}")
            return ""

    def _trigger_llm_response_generation(self):
        self.action_button.config(state=tk.DISABLED)
        self.voice_button.config(state=tk.DISABLED)
        # Do not disable speech_toggle_button, user might want to toggle speech mid-response generation
        self.input_field.config(state=tk.DISABLED)
        self.status_label.config(text="NovaCore Analyzing Request...")
        threading.Thread(target=self._get_and_process_llm_response_thread, daemon=True).start()

    def _get_and_process_llm_response_thread(self):
        try:
            if not self.conversation_history or self.conversation_history[-1]["role"] != "user":
                logging.warning("Attempted to generate response without preceding user input.")
                self.master.after(0, self._update_ui_after_llm, "Error: Internal state anomaly. No user input to respond to.")
                return

            llm_response = get_llm_response(self.conversation_history, TEMPERATURE, MAX_TOKENS)
            logging.debug("LLM Raw Response: %s", llm_response)
            # Schedule UI update and speech on the main thread
            self.master.after(0, self._update_ui_after_llm, llm_response) 
        except Exception as e: 
            logging.error(f"Critical error during LLM interaction thread: {e}", exc_info=True)
            self.master.after(0, self._update_ui_after_llm, f"Critical System Error: {e}")

    def _update_ui_after_llm(self, llm_response):
        # Display message first, then attempt to speak
        self.display_message(llm_response, sender="Nova", speak=False) # Display handles text
        self.conversation_history.append({"role": "assistant", "content": llm_response})
        
        # Conditional speech synthesis based on toggle
        if self.speech_synthesis_enabled and self.engine:
            try:
                # Stop any previous speech before starting new one,
                # in case of rapid responses or if user toggled speech off then on quickly.
                self.engine.stop()
                self.engine.say(llm_response)
                self.engine.runAndWait()
            except RuntimeError as e: # pyttsx3 can raise RuntimeError if used incorrectly (e.g. during an existing loop)
                logging.error(f"Error during speech synthesis (RuntimeError): {e}")
                # Try to re-initialize or recover if possible, or just log
                if "run loop already started" in str(e).lower():
                    logging.warning("Speech engine was already in a loop. Attempting to proceed.")
                else:
                    self.status_label.config(text="Audio Output Error.")
            except Exception as e:
                logging.error(f"Error during speech synthesis: {e}")
                self.status_label.config(text="Audio Output Error.")

        self.status_label.config(text="Awaiting Input...") # Clear status or set to ready
        self.action_button.config(state=tk.NORMAL)
        self.voice_button.config(state=tk.NORMAL)
        self.input_field.config(state=tk.NORMAL)
        if not self.input_field.get(): # If input field is empty after response
            self.on_entry_focus_out(None) # Re-apply placeholder if needed

    def display_message(self, message, sender="System", speak=False): # Added 'speak' parameter, default False
        self.chat_log.config(state=tk.NORMAL)
        if self.chat_log.index('end-1c') != "1.0": 
            self.chat_log.insert(tk.END, "\n\n") # Add more space between messages
        
        sender_tag = f"{sender}_tag"
        self.chat_log.tag_configure(sender_tag, font=self.bold_font)
        if sender == "Nova":
            self.chat_log.tag_configure(sender_tag, foreground=self.accent_color) # Nova in accent
        else: # Operator or System
            self.chat_log.tag_configure(sender_tag, foreground=self.text_color)


        self.chat_log.insert(tk.END, f"{sender}: ", sender_tag)
        self.chat_log.insert(tk.END, message) # Message in base font/color
        self.chat_log.config(state=tk.DISABLED)
        self.chat_log.yview(tk.END) 

        # Initial greeting speech is handled here, subsequent ones in _update_ui_after_llm
        if speak and self.speech_synthesis_enabled and self.engine:
             try:
                self.engine.stop()
                self.engine.say(message)
                self.engine.runAndWait()
             except Exception as e:
                logging.error(f"Error during initial speech synthesis: {e}")


    def on_closing(self):
        if messagebox.askokcancel("Deactivate NovaChat", "Confirm deactivation of NovaChat Terminal?"):
            logging.info("NovaChat Terminal shutting down.")
            if self.engine:
                self.engine.stop() # Ensure any ongoing speech is stopped
            self.master.destroy()
            # Note: Flask thread is daemon, will exit when main thread exits.
            
# -----------------------------------------------------------------------------
# Flask Routes (for web interface, if used)
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    # This requires a 'templates' folder in the same directory as chatbot.py,
    # and an 'index.html' file inside 'templates'.
    # e.g., templates/index.html
    try:
        return render_template("index.html") 
    except Exception as e:
        logging.error(f"Could not render index.html: {e}. Ensure 'templates/index.html' exists.")
        return "NovaChat Web Interface. Error: Template not found. See logs.", 500


@app.route("/get_response_http", methods=["POST"])
def get_response_http_route(): # Renamed to avoid conflict with internal function name
    try:
        data = request.get_json()
        if not data or "message" not in data:
            logging.error("Flask: Invalid request, 'message' field missing.")
            return jsonify({"status": "error", "message": "Invalid request, 'message' field missing."}), 400

        user_input_text = data["message"]
        logging.debug("Received user input in Flask: %s", user_input_text)
        
        # For Flask, conversation history can be managed per session or be stateless.
        # Here, we create a simple, stateless history for each request.
        flask_conversation_history = [
            {"role": "system", "content": "You are a helpful AI assistant responding via HTTP."},
            {"role": "user", "content": user_input_text}
        ]
        
        llm_response = get_llm_response(flask_conversation_history, TEMPERATURE, MAX_TOKENS)
        logging.debug("LLM response for Flask: %s", llm_response)
        return jsonify({"status": "success", "response": llm_response})
    except Exception as e:
        logging.error(f"Error in Flask route /get_response_http: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# -----------------------------------------------------------------------------
# Main Function
# -----------------------------------------------------------------------------
def main():
    # Ensure 'templates' directory exists for Flask, if not, create it
    # import os
    # if not os.path.exists("templates"):
    #     os.makedirs("templates")
    #     # You might want to create a placeholder index.html here too
    #     with open("templates/index.html", "w") as f:
    #         f.write("<h1>NovaChat Web (Placeholder)</h1><p>This is a basic web interface.</p>")
    #     logging.info("Created 'templates' directory and a placeholder index.html.")

    root = ThemedTk(theme="equilux") # equilux is a good dark theme
    chatbot_gui = ChatbotGUI(root)
    
    # Start Flask server in a separate thread
    # Use '0.0.0.0' to make it accessible on the network
    flask_kwargs = {'host': '0.0.0.0', 'port': 5000, 'debug': False, 'use_reloader': False}
    flask_thread = threading.Thread(target=app.run, kwargs=flask_kwargs, daemon=True)
    flask_thread.start()
    logging.info("Flask server starting in a daemon thread on http://0.0.0.0:5000.")
    
    root.mainloop()

if __name__ == "__main__":
    main()
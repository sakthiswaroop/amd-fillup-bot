# AMD Fillup Bot 🤖⛽

A Python + Selenium automation bot that streamlines the AMD “fillup” workflow (login → navigation → action).

> ⚠️ Disclaimer: Use only on systems/accounts you own or are authorized to access. This project is shared for learning and portfolio purposes.

---

## 🚀 Features
- Automated login and workflow navigation
- Supports headless and non-headless execution
- Environment-based configuration (no hardcoded credentials)
- Structured and clean project setup

---

## 🛠 Tech Stack
- Python
- Selenium WebDriver

---

## 📦 Installation

### 1️⃣ Clone the repository
git clone https://github.com/sakthiswaroop/amd-fillup-bot.git  
cd amd-fillup-bot  

### 2️⃣ Create virtual environment
python -m venv venv  

Activate (Windows):
venv\Scripts\activate  

### 3️⃣ Install dependencies
pip install -r requirements.txt  

---

## ⚙️ Configuration

Create a `.env` file (use `.env.example` as reference):

AMD_USERNAME=your_username  
AMD_PASSWORD=your_password  
AMD_BASE_URL=https://example.com  
HEADLESS=true  

---

## ▶️ Run the Bot
python main.py  

---

## 📌 Future Improvements
- Add CLI arguments
- Improve logging & error handling
- Add retry logic
- Refactor into modular structure

---

## 📜 License
MIT
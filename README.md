# MigrateKit — Windows 11 Migration Utility & E-Commerce Landing Page

A complete, professional suite comprising a Windows 11 migration application, VM verification protocol scripts, and an interactive Three.js-based landing page storefront.

---

## Project Structure

```
├── app/                          # Stage 1: Desktop Application
│   ├── migratekit.py             # Python CustomTkinter application
│   ├── requirements.txt          # App dependency list
│   └── build.bat                 # PyInstaller dynamic build script
│
├── docs/                         # Stage 2: VM Testing Environment
│   ├── testing_guide.md          # VM configuration walkthrough
│   └── scripts/                  # Troubleshooting PowerShell utilities
│       ├── verify_integrity.ps1  # Compares restored files vs. manifest
│       ├── test_chrome.ps1       # Validates Chrome databases/bookmarks
│       └── fix_permissions.ps1   # Resets folder locks & owner rights
│
├── website/                      # Stage 3: Interactive Storefront
│   ├── index.html                # Main landing page & modal checkout
│   ├── style.css                 # Glassmorphic responsive dark layout
│   └── app.js                    # Three.js 3D animations & key generator
│
├── serverless-backend/           # Serverless webhooks backend template
│   ├── netlify/
│   │   └── functions/
│   │       └── paypal-webhook.js # Netlify serverless webhook handler
│   └── README.md                 # Deployment guides
│
├── .gitignore
└── README.md
```

---

## Quick Start & Verification

### 1. Compile the Desktop App
Ensure Python is installed on your system. Navigate to the `app` directory and compile:
```cmd
cd app
build.bat
```
The compiled executable will be outputted to `app/dist/MigrateKit.exe`.

### 2. Launch the Web Storefront
Serve the e-commerce storefront locally to test Three.js rendering and checkout:
```cmd
cd website
python -m http.server 8000
```
Open your browser to `http://localhost:8000`.

- Click **Purchase License Key** under the premium card.
- Click **Simulate Checkout** or **Instant License Key Generation**.
- Copy the generated 20-digit key.
- Open `MigrateKit.exe`, paste the key into the **License Activation** tab, and verify activation!
- You can also bypass activation by typing the hardcoded developer key:
  `DEVKEY-MIGRATE-2026-UNLOCK`

---

## Deployment to GitHub Pages

To commit, push, and activate the storefront landing page on your GitHub repository:

1. Create a repository on GitHub named `MigrateKit` under the username `Jamezboi`.
2. Open Git Bash/PowerShell and run:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: MigrateKit Desktop App and Storefront"
   git branch -M main
   git remote add origin https://github.com/Jamezboi/MigrateKit.git
   git push -u origin main
   ```
3. Enable GitHub Pages:
   - Go to your repository settings on GitHub.
   - Click **Pages** on the left menu.
   - Set Source to **Deploy from branch**.
   - Under Branch, select `main` and set folder path to `/website` (or keep root `/` if you want to expose files).
   - Click **Save**. Your site will deploy at:
     `https://jamezboi.github.io/MigrateKit/`

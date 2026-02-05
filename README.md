<div align="center">
  <img src="ui/static/img/logo.png" alt="OMSI 2 Mod Manager Logo" width="120" height="120">
  
  <h1 align="center">OMSI 2 Mod Manager</h1>

  <p align="center">
    <strong>A next-generation tool for managing your OMSI 2 library safely and efficiently.</strong>
    <br />
    Developed with ❤️ by <a href="https://github.com/Bongo94"><strong>Bongo94</strong></a>
  </p>

  <p align="center">
    <!-- Language Switcher -->
    <a href="README.md"><strong>English</strong></a> | <a href="README.ru.md"><strong>Русский</strong></a>
  </p>

  <p align="center">
    <a href="#-key-features">Features</a> •
    <a href="#-how-to-use-guide">How to Use</a> •
    <a href="#-faq">FAQ</a> •
    <a href="#%EF%B8%8F-installation--build">Installation</a>
  </p>

  <div align="center">
      <a href="../../releases/latest">
        <img src="https://img.shields.io/badge/DOWNLOAD-LATEST_VERSION-orange?style=for-the-badge&logo=windows&logoColor=white" alt="Download">
      </a>
  </div>

  ![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
  ![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)
  ![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
</div>

<br />

![Application Screenshot](ui/static/img/screenshot.png)

---

## 🚌 About The Project

**OMSI 2 Mod Manager** solves the chaos of installing add-ons. Unlike the traditional "copy-paste" method that clutters your game folder, this manager uses a **Symlink-based system**.

Your mods are stored in a separate, clean **Library**. When you enable a mod, the manager creates "phantom links" in the game folder. The game sees the files, but your disk space isn't duplicated, and you can remove mods instantly without breaking the game.

## ✨ Key Features

*   **📦 Smart Import:** Supports ZIP, RAR, and 7Z archives. Powered by an embedded **7-Zip engine** for maximum speed.
*   **🛡️ Safety First:** Non-destructive installation. Original game files are backed up automatically if a mod replaces them.
*   **🚌 HOF Manager:** A unique tool to "inject" `.hof` files into specific buses without manually copying files to 50 different folders.
*   **⚠️ Conflict Solver:** Detects if two mods try to edit the same texture or script. You choose the priority via a drag-and-drop **Load Order**.
*   **🌍 Multilingual:** English and Russian interface (switchable).
*   **🎨 Modern Design:** Dark mode UI with orange accents, inspired by sci-fi dashboards.

---

## 📖 How to Use (Guide)

### 1. First Setup
When you launch the app for the first time, you need to configure two paths:
*   **OMSI 2 Root Directory:** The folder where `Omsi.exe` is located (e.g., `Steam\steamapps\common\OMSI 2`).
*   **Mod Library Storage:** An empty folder (preferably on the same disk) where the manager will store unpacked mod archives. **Do not delete this folder!**

### 2. Installing a Mod
1.  Click **"Install Mod"** (or "+").
2.  Select an archive (`.zip`, `.rar`, `.7z`).
3.  **Review Screen:** The manager will analyze the file structure.
    *   Files marked in **Green**/Yellow are recognized and mapped correctly.
    *   Files in **Red** (Ignored) are usually useless text files or URLs that don't need to be in the game.
4.  Click **"Confirm"**. The mod is now imported into your Library.
5.  In the main list, click the **Toggle Button** (⏯) to enable the mod in the game.

### 3. Using the HOF Manager
Stop copying `.hof` files manually!
1.  Open **HOF Manager**.
2.  **Left Column:** Select the HOF file(s) you want to use. You can even import existing HOFs from your game folder.
3.  **Right Column:** Select the buses you want to install these HOFs into.
4.  Click **"Inject HOF Files"**.
5.  The manager creates symlinks in the selected bus folders. You can remove them all later with one click ("Reset All").

### 4. Resolving Conflicts
If you have texture mods or sound mods that touch the same files:
1.  Click **"Load Order"**.
2.  You will see a list of conflicting mods.
3.  **The Mod at the TOP (No. 1)** has the highest priority and will overwrite mods below it.
4.  Reorder them and click "Apply".

---

## ❓ FAQ

**Q: What are Symlinks?**
A: A Symbolic Link is a shortcut that acts like a real file. OMSI 2 thinks the file is inside the `Vehicles` folder, but it actually stays in your `Mod Library`. This saves disk space and keeps the game clean.

**Q: Can I delete the "Mod Library" folder?**
A: **No!** That folder contains the actual files. If you delete it, your mods will stop working.

**Q: I deleted a mod, but the game is broken.**
A: The manager has a backup system. When you disable or delete a mod, the manager attempts to restore the original game file (if it existed).

**Q: My antivirus flagged the `.exe`.**
A: This is a common "false positive" for Python applications compiled with PyInstaller. The code is open source, and you can build it yourself to be sure.

---

## 🛠️ Installation & Build

### For Users
1.  Go to the **[Releases](../../releases)** page.
2.  Download `OMSI2 Mod Manager.exe`.
3.  Run it (Portable).

### For Developers
1.  Clone repo: `git clone https://github.com/Bongo94/OMSI2-ModManager.git`
2.  Install requirements: `pip install -r requirements.txt`
3.  Run: `python main.py`
4.  **Build EXE:**
    ```bash
    pyinstaller --noconsole --onefile --name="OMSI2 Mod Manager by Bongo94" --icon="app.ico" --add-data "ui;ui" --add-data "7Zip;7Zip" main.py
    ```

---

## 👤 Author

**Bongo94**
*   GitHub: [@Bongo94](https://github.com/Bongo94)

---
<div align="center">
  <sub>Built for the OMSI community. Drive safe! 🚌</sub>
</div>
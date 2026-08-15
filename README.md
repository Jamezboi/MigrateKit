# MigrateKit — Windows 11 Migration Utility

MigrateKit is a Windows migration utility with a CustomTkinter desktop application and a Three.js storefront hosted directly from the repository root on GitHub Pages.

## Project Structure

```text
├── app/
│   ├── migratekit.py
│   ├── requirements.txt
│   └── build.bat
├── docs/
│   ├── testing_guide.md
│   └── scripts/
│       ├── verify_integrity.ps1
│       ├── test_chrome.ps1
│       └── fix_permissions.ps1
├── index.html
├── style.css
├── app.js
├── serverless-backend/
├── .github/workflows/
│   ├── build-release.yml
│   └── pages.yml
├── .gitignore
└── README.md
```

## Windows application

From a Windows machine with Python installed:

```cmd
cd app
build.bat
```

The build script installs dependencies, applies the known `MigrateKitApp` AppData compatibility fix, runs `py_compile`, builds a one-file Windows executable with PyInstaller, and verifies `dist/MigrateKit.exe`.

## Storefront

The storefront is the repository root. There is intentionally **no `/website` directory**.

Run it locally with:

```cmd
python -m http.server 8000
```

Then open `http://localhost:8000/`.

The page loads `style.css` and `app.js` using root-relative document paths, while Three.js is loaded from its public CDN module URL.

## GitHub Pages

The `pages.yml` workflow deploys the repository root directly to GitHub Pages. After Pages is enabled for the repository using **GitHub Actions** as the source, the storefront is published at:

`https://jamezboi.github.io/MigrateKit/`

## Releases

The Windows workflow builds the executable on `windows-latest`, validates the resulting file, uploads it as an Actions artifact, and publishes the fixed build as GitHub release `v1.0.1` with `MigrateKit.exe` attached.

## License

MigrateKit uses the project license-validation mechanism implemented in `app/migratekit.py`. The developer bypass key is intended only for development/testing and should not be exposed in a production build.

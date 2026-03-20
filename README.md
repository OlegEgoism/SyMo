# SyMo (JavaScript + CSS Rewrite)

SyMo is now fully rewritten from Python to **JavaScript** with a CSS-based UI layer.

## Stack

- Node.js 20+
- JavaScript (ES Modules)
- CSS for dashboard styling
- `systeminformation` for host metrics
- `axios` for Telegram/Discord notifications

## New structure

```text
SyMo/
├─ app.js
├─ package.json
├─ app_core/
│  ├─ app.js
│  ├─ click_tracker.js
│  ├─ constants.js
│  ├─ dialogs.js
│  ├─ language.js
│  ├─ localization.js
│  ├─ logging_utils.js
│  ├─ power_control.js
│  └─ system_usage.js
├─ notifications/
│  ├─ telegram.js
│  └─ discord.js
└─ ui/
   └─ styles.css
```

## Run

```bash
npm install
npm run start
```

## Lint / syntax check

```bash
npm run lint
```

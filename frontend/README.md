# Sepsis Bundle Frontend

Static zero-build frontend for the five-agent governed Sepsis Bundle project.

## Screens
- Clinical Assessment: structured SOFA + antibiotic inputs and governed output.
- Governance: policy matrix and safety boundaries.
- Memory & Analytics: aggregate-only analytics view.
- Five-Agent System: Acequia-inspired architecture visualization.

## API
The UI calls the same-origin API by default:
- `GET /health`
- `POST /assess`
- `GET /analytics`

For a separately hosted API, set `window.SEPSIS_API_BASE` before loading `app.js`.

## Safety boundary
The frontend is display/orchestration UI only. It does not generate or approve clinical recommendations. The backend Governance Layer remains authoritative; blocked antibiotic recommendations are not promoted by the UI.

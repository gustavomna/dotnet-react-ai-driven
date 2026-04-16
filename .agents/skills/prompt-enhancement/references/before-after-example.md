# Example: Base Prompt vs Structured Prompt

## Base Prompt (typical input)

```
Implement a weather dashboard on the existing frontend and backend.

The user should be able to type a city and see the current weather.

To get the data, use the Open-Meteo API (free, no API key required):

• Geocoding API: https://geocoding-api.open-meteo.com/v1/search (convert city to coordinates)
• Weather API: https://api.open-meteo.com/v1/forecast (get weather data)

The frontend should fetch data only from the backend. Optionally, the frontend can try to obtain the user's location via the browser (geolocation) and suggest the city automatically.

Create an endpoint on the backend for the frontend to consume and display the data on the dashboard.
```

## Problems with the base prompt

- Does not define the agent role
- Mixed requirements (business, technical, UI)
- Missing endpoint specification (method, status codes)
- Does not mention project skills
- Does not define out of scope
- Missing UI/UX details (loading, errors, responsiveness)

## Structured Prompt (expected output)

See `assets/structured-prompt-template.md` for the full template. The result should:

1. Extract the task into `<task>`
2. Define `<goals>` (one focusing sentence)
3. Define `<role>` with context and stack
4. Separate `<requirements>` into Business, Technical, UI/UX
5. Include `<workflow>` for tasks with multiple steps
6. Define `<output>` when the output format is relevant
7. Document `<endpoints>` with URLs, methods, status codes
8. Include `<tests>` when there are endpoints
9. List `<critical>`: required skills and out of scope
10. Use `---` as a delimiter between long blocks

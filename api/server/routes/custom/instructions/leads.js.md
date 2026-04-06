# To use this route, paste this schema to the add action schema in the agent builder:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Lead Capture API",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "http://localhost:3080"
    }
  ],
  "paths": {
    "/api/leads": {
      "post": {
        "operationId": "save_lead",
        "summary": "Save a visitor lead",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "name": { "type": "string" },
                  "company": { "type": "string" },
                  "email": { "type": "string" },
                  "phone": { "type": "string" },
                  "industry": { "type": "string" },
                  "facilities": { "type": "string" },
                  "notes": { "type": "string" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Lead saved successfully"
          }
        }
      }
    }
  }
}
```
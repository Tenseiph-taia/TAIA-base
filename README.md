<br>

<div align="center">
     <div style="width: 400px; height: 120px; display: flex; align-items: center; justify-content: center;">
        <img src="client/public/assets/taia_mascott_nobg.png" alt="TAIA Logo" width="160">
    </div>
    
# TAIA for Tensei Philippines Inc.
</div>

## Project Overview

TAIA, short for **Tensei AI Agent**, is a self-hosted AI chat platform that unifies all major AI providers in a single, privacy-focused interface. It empowers users with AI Agents, Model Context Protocol (MCP) support, Artifacts, and a secure Code Interpreter, providing a comprehensive ecosystem for AI-driven productivity. Designed for scalability and control, TAIA allows for complete ownership of AI infrastructure.

## Tech Stack & Tools

This project uses the following technologies:

![Node.js](https://img.shields.io/badge/Node.js-20.x-green?logo=nodedotjs)
![MongoDB](https://img.shields.io/badge/MongoDB-Community-green?logo=mongodb)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-blue?logo=typescript)
![React](https://img.shields.io/badge/React-18.x-61DAFB?logo=react)
![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3.x-06B6D4?logo=tailwindcss)
![Vite](https://img.shields.io/badge/Vite-latest-yellow?logo=vite)
![Redis](https://img.shields.io/badge/Redis-latest-DC3823?logo=redis)
![Docker](https://img.shields.io/badge/Docker-latest-2496ED?logo=docker)

## Installation & Setup

Follow the steps below to set up the project locally.

### ⚠️ Prerequisites

Ensure you have **Docker** and **Docker Compose** properly installed and configured on your local machine.

<br>

1. Clone the **repository**.

    ```sh
    git clone https://github.com/Tenseiph-taia/TAIA-base.git
    ```   
    <br>

2. Navigate to the project's **root directory**.

    ```sh
    cd TAIA-base
    ```   
    <br>

3. Create a `.env` file from the `.env.example`.  
   TAIA requires environment variables for API keys, database connections, and application secrets.

    ```sh
    cp .env.example .env
    ```   
    <br>

4. Configure your **Environment Variables**.
   Update the `.env` file with your preferred API keys (Anthropic, OpenAI, Azure, etc.) and any other required settings.
   
   **Note:** For local development and testing, **Ollama** is used to run and test local AI models. Ensure Ollama is installed and running on your host machine to utilize local models.
    <br>

5. Deploy the application using **Docker Compose**.
   This will automatically pull the required images, set up the network, and start the backend, frontend, and database services.

    ```sh
    docker compose up -d
    ```
    The `-d` flag runs the containers in detached mode in the background.
    <br>

6. Access the application.
   Once the containers are running, the application will typically be accessible at:
   - **Frontend:** `http://localhost:3090`
   - **Backend API:** `http://localhost:3080`
    <br>

7. Manage the containers.
   To view the logs of the running services, use:

    ```sh
    docker compose logs -f
    ```
    To stop the application, run:

    ```sh
    docker compose down
    ```

## Usage

Once the application is installed and running, you can begin development or testing.

1. **Updating Localizations**:
   To add or change user-facing text, update the English keys in `client/src/locales/en/translation.json`.
   <br>

2. **Container Maintenance**:
   If you make changes to the `.env` file, restart the containers to apply the changes:

    ```sh
    docker compose restart
    ```
    <br>

3. **Build for Production**:
   To compile all code in the monorepo for production:

    ```sh
    npm run build
    ```

## ✨ Key Features

- 🤖 **AI Model Selection**: Integration with Anthropic, OpenAI, Azure, Google, and Local providers (Ollama).
- 🔧 **Code Interpreter**: Secure, sandboxed execution for Python, Node.js, and more.
- 🔦 **AI Agents**: No-code custom assistants with MCP Server support.
- 🪄 **Artifacts**: Generative UI allowing React, HTML, and Mermaid diagrams directly in chat.
- 🌊 **Resumable Streams**: Automatic reconnection and resume for AI responses.
- 👥 **Secure Access**: Multi-user authentication with OAuth2 and LDAP support.

<br>

[Back to Top](#project-overview)

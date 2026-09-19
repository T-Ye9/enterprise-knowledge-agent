import { defineRailway, github, preserve, project, service } from "railway/iac";

export default defineRailway((ctx) => {
  if (!ctx.projectName) {
    throw new Error("Link the intended Railway project before planning or applying.");
  }

  const backend = service("backend", {
    source: github("T-Ye9/enterprise-knowledge-agent", { branch: "main" }),
    replicas: 1,
    healthcheck: "/health",
    healthcheckTimeout: 300,
    env: {
      APP_ENV: "production",
      ALLOW_DOCUMENT_UPLOAD: "false",
      BOOTSTRAP_DEMO_KNOWLEDGE_BASE: "true",
      KNOWLEDGE_DB_PATH: "/app/data/vector-db",
      EMBEDDING_CACHE_DIR: "/app/.cache/embeddings",
      DEEPSEEK_BASE_URL: "https://api.deepseek.com",
      DEEPSEEK_MODEL: "deepseek-flash",
      DEEPSEEK_API_KEY: preserve(),
      CORS_ORIGINS: preserve(),
    },
  });

  return project(ctx.projectName, { resources: [backend] });
});

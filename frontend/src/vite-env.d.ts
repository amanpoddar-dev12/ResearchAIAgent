interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly VITE_API_URL?: string;
  readonly VITE_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

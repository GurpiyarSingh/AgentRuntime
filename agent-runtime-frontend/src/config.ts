/** Build-time configuration, read from VITE_* environment variables (see .env.example). */

/** Backend origin; empty means same-origin (dev proxy or reverse proxy). */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

/** Folder in the workspace that attachments are uploaded to. */
export const UPLOAD_FOLDER = 'uploads/';

// On a real phone "localhost" is the phone itself. Set EXPO_PUBLIC_API_URL to your
// computer's address on the same Wi-Fi, e.g. http://192.168.1.20:8001
export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8001";
export const API_V1 = `${API_URL}/api/v1`;

// Where the website lives, for the policy pages the app links to.
export const SITE_URL = process.env.EXPO_PUBLIC_SITE_URL ?? "http://localhost:3000";

const appJson = require('./app.json');

/** Keep the device API URL in the native Expo manifest as well as the JS env. */
module.exports = () => ({
  ...appJson.expo,
  extra: {
    ...(appJson.expo.extra ?? {}),
    apiUrl: process.env.EXPO_PUBLIC_API_URL?.trim() || 'https://run-backend-ngyo.onrender.com',
  },
});

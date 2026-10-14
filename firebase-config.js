import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import { getDatabase } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";

const firebaseConfig = {
  apiKey: "AIzaSyBT-h3T1JpZH7zSV5avMSb2BXutcm9MQZQ",
  authDomain: "msu-laptopmonitoringsystem.firebaseapp.com",
  databaseURL: "https://msu-laptopmonitoringsystem-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "msu-laptopmonitoringsystem",
  storageBucket: "msu-laptopmonitoringsystem.firebasestorage.app",
  messagingSenderId: "307496882491",
  appId: "1:307496882491:web:59259393fa120a17a0a71e"
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getDatabase(app);

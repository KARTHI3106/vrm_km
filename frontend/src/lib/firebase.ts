import { initializeApp } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  sendPasswordResetEmail,
  type User,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyDZ1xjBQE8L0Y2QjIQAQpgA9Y3uGDQ9tAA",
  authDomain: "ml-ai-navigator.firebaseapp.com",
  projectId: "ml-ai-navigator",
  storageBucket: "ml-ai-navigator.firebasestorage.app",
  messagingSenderId: "790394519130",
  appId: "1:790394519130:web:c4e3e99ec1d93afda3a263",
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

export {
  auth,
  googleProvider,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  sendPasswordResetEmail,
};
export type { User };

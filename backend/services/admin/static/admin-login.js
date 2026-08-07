import { initializeApp } from "https://www.gstatic.com/firebasejs/12.17.1/firebase-app.js";
import {
  GoogleAuthProvider,
  getAuth,
  inMemoryPersistence,
  setPersistence,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/12.17.1/firebase-auth.js";

const button = document.querySelector("#google-sign-in");
const status = document.querySelector("#login-status");

function showStatus(message, error = false) {
  status.textContent = message;
  status.classList.remove("hidden", "border-red-300/30", "bg-red-300/10", "text-red-100", "border-amber-300/30", "bg-amber-300/10", "text-amber-100");
  status.classList.add(...(error
    ? ["border-red-300/30", "bg-red-300/10", "text-red-100"]
    : ["border-amber-300/30", "bg-amber-300/10", "text-amber-100"]));
}

button?.addEventListener("click", async () => {
  button.disabled = true;
  showStatus("Opening secure sign-in…");
  const firebaseApp = initializeApp({
    apiKey: button.dataset.apiKey,
    authDomain: button.dataset.authDomain,
    projectId: button.dataset.projectId,
    appId: button.dataset.appId,
  });
  const auth = getAuth(firebaseApp);
  try {
    await setPersistence(auth, inMemoryPersistence);
    const credential = await signInWithPopup(auth, new GoogleAuthProvider());
    const idToken = await credential.user.getIdToken(true);
    const response = await fetch("/admin/session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id_token: idToken,
        csrf_token: button.dataset.csrfToken,
      }),
    });
    if (!response.ok) {
      throw new Error(response.status === 403 ? "This account is not authorized." : "Sign-in could not be completed.");
    }
    const result = await response.json();
    await signOut(auth);
    window.location.assign(result.redirect);
  } catch (error) {
    showStatus(error?.message || "Sign-in could not be completed.", true);
    button.disabled = false;
  }
});

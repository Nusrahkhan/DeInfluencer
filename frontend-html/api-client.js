/**
 * API utility functions for frontend
 * All API calls go through this file
 */

const API_BASE_URL = "http://127.0.0.1:8000";

class APIClient {
  /**
   * Sign up new user
   * @param {string} name - User's name
   * @param {string} email - User's email
   * @param {string} password - User's password
   * @param {string} confirmPassword - Password confirmation
   * @returns {Promise<Object>}
   */
  static async signup(name, email, password, confirmPassword) {
    const response = await fetch(`${API_BASE_URL}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        email,
        password,
        confirm_password: confirmPassword,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Signup failed");
    }
    return data;
  }

  /**
   * Verify OTP
   * @param {string} email - User's email
   * @param {string} otp - 6-digit OTP
   * @returns {Promise<Object>}
   */
  static async verifyOTP(email, otp) {
    const response = await fetch(`${API_BASE_URL}/auth/verify-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, otp }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "OTP verification failed");
    }
    return data;
  }

  /**
   * Resend OTP
   * @param {string} email - User's email
   * @returns {Promise<Object>}
   */
  static async resendOTP(email) {
    const response = await fetch(`${API_BASE_URL}/auth/resend-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Failed to resend OTP");
    }
    return data;
  }

  /**
   * Sign in user
   * @param {string} email - User's email
   * @param {string} password - User's password
   * @returns {Promise<Object>}
   */
  static async signin(email, password) {
    const response = await fetch(`${API_BASE_URL}/auth/signin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Sign in failed");
    }
    return data;
  }

  /**
   * Submit quiz answers
   * @param {string} email - User's email
   * @param {Object} answers - Quiz answers object
   * @returns {Promise<Object>}
   */
  static async submitQuiz(email, answers) {
    const token = localStorage.getItem("auth_token");
    
    const response = await fetch(`${API_BASE_URL}/auth/submit-quiz`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        email,
        ...answers,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Quiz submission failed");
    }
    return data;
  }

  /**
   * Get user profile
   * @param {string} email - User's email
   * @returns {Promise<Object>}
   */
  static async getProfile(email) {
    const token = localStorage.getItem("auth_token");
    
    const response = await fetch(`${API_BASE_URL}/auth/profile?email=${email}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Failed to fetch profile");
    }
    return data;
  }
}

/**
 * Local Storage Management
 */
const Storage = {
  setSignupEmail(email) {
    localStorage.setItem("signup_email", email);
  },

  getSignupEmail() {
    return localStorage.getItem("signup_email");
  },

  setAuthToken(token) {
    localStorage.setItem("auth_token", token);
  },

  getAuthToken() {
    return localStorage.getItem("auth_token");
  },

  setUserEmail(email) {
    localStorage.setItem("user_email", email);
  },

  getUserEmail() {
    return localStorage.getItem("user_email");
  },

  setUserName(name) {
    localStorage.setItem("user_name", name);
  },

  getUserName() {
    return localStorage.getItem("user_name");
  },

  setQuizCompleted(status) {
    localStorage.setItem("quiz_completed", status);
  },

  getQuizCompleted() {
    return localStorage.getItem("quiz_completed");
  },

  clear() {
    localStorage.clear();
  },
};

/**
 * UI Helper functions
 */
const UIHelpers = {
  showLoading(button, message = "Loading...") {
    button.disabled = true;
    button.innerHTML = `<span class="material-symbols-outlined" style="animation: spin 1s linear infinite;">progress_activity</span> ${message}`;
  },

  hideLoading(button, originalText) {
    button.disabled = false;
    button.innerHTML = originalText;
  },

  showError(message) {
    alert(`❌ ${message}`);
  },

  showSuccess(message) {
    alert(`✅ ${message}`);
  },

  redirectTo(url) {
    setTimeout(() => {
      window.location.href = url;
    }, 1000);
  },
};

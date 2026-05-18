import { useState } from "react";
import { createClient } from "@supabase/supabase-js";

// -------------------- SUPABASE --------------------
const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

// -------------------- STYLES --------------------
const styles = `
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;1,700&family=DM+Sans:wght@300;400;500;600&display=swap');

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.signup-root {
  min-height: 100vh;
  background: #FDF0EC;
  font-family: 'DM Sans', sans-serif;
  color: #1A0A08;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.signup-card {
  width: 100%;
  max-width: 760px;
  background: #FFF8F6;
  border-radius: 32px;
  padding: 42px;
  box-shadow: 0 20px 60px rgba(0,0,0,.08);
  border: 1px solid #FAD4CF;
  animation: fadeUp .5s ease;
}

@keyframes fadeUp {
  from {
    opacity: 0;
    transform: translateY(18px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.signup-logo {
  font-family: 'Playfair Display', serif;
  color: #E8453C;
  font-style: italic;
  font-size: 28px;
  margin-bottom: 10px;
}

.signup-title {
  font-family: 'Playfair Display', serif;
  font-size: clamp(32px, 5vw, 52px);
  line-height: 1.1;
  margin-bottom: 14px;
}

.signup-title em {
  color: #E8453C;
  font-style: italic;
}

.signup-subtitle {
  color: #7A4A45;
  font-size: 15px;
  line-height: 1.7;
  margin-bottom: 36px;
  max-width: 520px;
}

.signup-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.signup-field {
  display: flex;
  flex-direction: column;
}

.signup-field-full {
  grid-column: span 2;
}

.signup-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #1A0A08;
}

.signup-input,
.signup-select,
.signup-textarea {
  border: 1.5px solid #FAD4CF;
  background: white;
  border-radius: 18px;
  padding: 14px 16px;
  font-size: 14px;
  font-family: 'DM Sans', sans-serif;
  outline: none;
  transition: border-color .2s, box-shadow .2s;
}

.signup-input:focus,
.signup-select:focus,
.signup-textarea:focus {
  border-color: #E8453C;
  box-shadow: 0 0 0 4px rgba(232,69,60,.08);
}

.signup-textarea {
  resize: vertical;
  min-height: 110px;
}

.signup-chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.signup-chip {
  border: 1.5px solid #FAD4CF;
  background: white;
  color: #1A0A08;
  padding: 10px 14px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  transition: all .2s;
}

.signup-chip:hover {
  border-color: #E8453C;
}

.signup-chip.active {
  background: #E8453C;
  border-color: #E8453C;
  color: white;
}

.signup-btn {
  margin-top: 30px;
  width: 100%;
  border: none;
  background: #E8453C;
  color: white;
  padding: 16px;
  border-radius: 18px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background .2s, transform .2s;
}

.signup-btn:hover {
  background: #cc372f;
  transform: translateY(-1px);
}

.signup-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.signup-success {
  margin-top: 20px;
  background: #d4edda;
  color: #2e7d32;
  padding: 14px 18px;
  border-radius: 14px;
  font-size: 14px;
}

.signup-error {
  margin-top: 20px;
  background: #fde2e1;
  color: #c62828;
  padding: 14px 18px;
  border-radius: 14px;
  font-size: 14px;
}

@media (max-width: 700px) {
  .signup-card {
    padding: 28px 20px;
  }

  .signup-grid {
    grid-template-columns: 1fr;
  }

  .signup-field-full {
    grid-column: span 1;
  }
}
`;

const skinConcernsOptions = [
  "Acne",
  "Dryness",
  "Pigmentation",
  "Dark Circles",
  "Sensitive Skin",
  "Large Pores",
  "Anti-Aging",
  "Redness",
  "Uneven Texture",
  "Oiliness",
];

export default function SignupPage() {
  const [loading, setLoading] = useState(false);

  const [formData, setFormData] = useState({
    full_name: "",
    email: "",
    age_range: "",
    skin_type: "",
    budget: "",
    makeup_style: "",
    skin_concerns: [],
    favorite_brands: "",
    allergies: "",
  });

  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  // -------------------- HANDLE INPUT --------------------
  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  // -------------------- CHIP TOGGLE --------------------
  const toggleConcern = (concern) => {
    const exists = formData.skin_concerns.includes(concern);

    if (exists) {
      setFormData({
        ...formData,
        skin_concerns: formData.skin_concerns.filter((c) => c !== concern),
      });
    } else {
      setFormData({
        ...formData,
        skin_concerns: [...formData.skin_concerns, concern],
      });
    }
  };

  // -------------------- SUBMIT --------------------
  const handleSubmit = async (e) => {
    e.preventDefault();

    setLoading(true);
    setError("");
    setSuccess("");

    const { error } = await supabase.from("user_profiles").insert([
      {
        full_name: formData.full_name,
        email: formData.email,
        age_range: formData.age_range,
        skin_type: formData.skin_type,
        budget: formData.budget,
        makeup_style: formData.makeup_style,
        skin_concerns: formData.skin_concerns,
        favorite_brands: formData.favorite_brands,
        allergies: formData.allergies,
      },
    ]);

    if (error) {
      setError(error.message);
    } else {
      setSuccess("Profile created successfully ✨");

      setFormData({
        full_name: "",
        email: "",
        age_range: "",
        skin_type: "",
        budget: "",
        makeup_style: "",
        skin_concerns: [],
        favorite_brands: "",
        allergies: "",
      });
    }

    setLoading(false);
  };

  return (
    <div className="signup-root">
      <style>{styles}</style>

      <div className="signup-card">
        <div className="signup-logo">deInfluence</div>

        <h1 className="signup-title">
          Build your <em>beauty profile.</em>
        </h1>

        <p className="signup-subtitle">
          Tell us about your skin, makeup preferences, and budget so we can
          recommend products that actually work for you — not just what’s viral.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="signup-grid">

            {/* FULL NAME */}
            <div className="signup-field">
              <label className="signup-label">Full Name</label>
              <input
                type="text"
                name="full_name"
                value={formData.full_name}
                onChange={handleChange}
                className="signup-input"
                placeholder="Your name"
                required
              />
            </div>

            {/* EMAIL */}
            <div className="signup-field">
              <label className="signup-label">Email</label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                className="signup-input"
                placeholder="you@example.com"
                required
              />
            </div>

            {/* AGE */}
            <div className="signup-field">
              <label className="signup-label">Age Range</label>
              <select
                name="age_range"
                value={formData.age_range}
                onChange={handleChange}
                className="signup-select"
                required
              >
                <option value="">Select</option>
                <option>13-18</option>
                <option>18-24</option>
                <option>25-34</option>
                <option>35-44</option>
                <option>45+</option>
              </select>
            </div>

            {/* SKIN TYPE */}
            <div className="signup-field">
              <label className="signup-label">Skin Type</label>
              <select
                name="skin_type"
                value={formData.skin_type}
                onChange={handleChange}
                className="signup-select"
                required
              >
                <option value="">Select</option>
                <option>Dry</option>
                <option>Oily</option>
                <option>Combination</option>
                <option>Normal</option>
                <option>Sensitive</option>
              </select>
            </div>

            {/* BUDGET */}
            <div className="signup-field">
              <label className="signup-label">Budget Preference</label>
              <select
                name="budget"
                value={formData.budget}
                onChange={handleChange}
                className="signup-select"
                required
              >
                <option value="">Select</option>
                <option>Budget Friendly</option>
                <option>Mid Range</option>
                <option>Luxury</option>
              </select>
            </div>

            {/* MAKEUP STYLE */}
            <div className="signup-field">
              <label className="signup-label">Makeup Style</label>
              <select
                name="makeup_style"
                value={formData.makeup_style}
                onChange={handleChange}
                className="signup-select"
              >
                <option value="">Select</option>
                <option>Natural</option>
                <option>Minimal</option>
                <option>Full Glam</option>
                <option>K-Beauty</option>
                <option>No Makeup Makeup</option>
              </select>
            </div>

            {/* SKIN CONCERNS */}
            <div className="signup-field signup-field-full">
              <label className="signup-label">
                Skin Concerns
              </label>

              <div className="signup-chip-group">
                {skinConcernsOptions.map((concern) => (
                  <button
                    type="button"
                    key={concern}
                    className={`signup-chip ${
                      formData.skin_concerns.includes(concern)
                        ? "active"
                        : ""
                    }`}
                    onClick={() => toggleConcern(concern)}
                  >
                    {concern}
                  </button>
                ))}
              </div>
            </div>

            {/* FAVORITE BRANDS */}
            <div className="signup-field signup-field-full">
              <label className="signup-label">
                Favorite Brands
              </label>

              <input
                type="text"
                name="favorite_brands"
                value={formData.favorite_brands}
                onChange={handleChange}
                className="signup-input"
                placeholder="e.g. The Ordinary, Rare Beauty..."
              />
            </div>

            {/* ALLERGIES */}
            <div className="signup-field signup-field-full">
              <label className="signup-label">
                Allergies / Ingredients to Avoid
              </label>

              <textarea
                name="allergies"
                value={formData.allergies}
                onChange={handleChange}
                className="signup-textarea"
                placeholder="Fragrance, alcohol, essential oils..."
              />
            </div>
          </div>

          <button
            type="submit"
            className="signup-btn"
            disabled={loading}
          >
            {loading ? "Creating Profile..." : "Create My Profile"}
          </button>

          {success && (
            <div className="signup-success">{success}</div>
          )}

          {error && (
            <div className="signup-error">{error}</div>
          )}
        </form>
      </div>
    </div>
  );
}
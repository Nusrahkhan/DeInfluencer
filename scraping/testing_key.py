import google.generativeai as genai

genai.configure(api_key="AIzaSyCoUN4fYT2lWPdwAdrcLPCp_dOzu15o0w0")

model = genai.GenerativeModel("gemini-2.0-flash")

response = model.generate_content("Explain recursion simply")
print(response.text)
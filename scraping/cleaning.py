import pandas as pd
from thefuzz import process
import re

# 1. Load the dataset
file_name = 'clinique_reviews_export.csv'
df = pd.read_csv(file_name)

# 2. Define your exact list of products (No additions or abbreviations)
clinique_products = [
    "Clinique2-In-1 Cleansing Micellar Gel + Light Makeup Remover",
    "Clinique7 Day Scrub Cream",
    "CliniqueAcne Solutions Acne + Line Correcting Serum",
    "CliniqueAcne Solutions All Over Clearing Treatment",
    "CliniqueAcne Solutions Clarifying Lotion",
    "CliniqueAcne Solutions Cleansing Foam",
    "CliniqueAcne Solutions Clearing Concealer",
    "CliniqueAcne Solutions Emergency Touch Stick",
    "CliniqueAcne Solutions Liquid Makeup Foundation",
    "CliniqueAcne Solutions Oil-Control Cleansing Mask",
    "CliniqueAcne Solutions™ Acne + Line Correcting Serum",
    "CliniqueAcne Solutions™ BB Cream SPF 40",
    "CliniqueAcne Solutions™ Cleansing Gel",
    "CliniqueAcne Solutions™ Clinical Clearing Gel",
    "CliniqueAcne Solutions™ Liquid Makeup",
    "CliniqueAdvanced Concealer",
    "CliniqueAfter Sun Rescue Balm With Aloe",
    "CliniqueAge Defense Bb Cream Broad Spectrum Spf 30",
    "CliniqueAirbrush Concealer",
    "CliniqueAll About Clean Facial Foaming Soap",
    "CliniqueAll About Clean Micellar Milk (Dry Skin)",
    "CliniqueAll About Clean Micellar Milk (Oily Combination Skin)",
    "CliniqueAll About Clean Rinse-off Foaming Face Cleanser",
    "CliniqueAll About Clean™ 2-in-1 Charcoal Face Mask + Scrub",
    "CliniqueAll About Clean™ 2-in-1 Cleansing + Exfoliating Jelly",
    "CliniqueAll About Clean™ Liquid Facial Soap",
    "CliniqueAll About Eyes(Discontinued)",
    "CliniqueAll About Eyes Brightening Serum Concentrate With Retinoid",
    "CliniqueAll About Eyes Eye Cream Rich",
    "CliniqueAll About Eyes Rich",
    "CliniqueAll About Eyes Rich (old formula)",
    "CliniqueAll About Eyes™",
    "CliniqueAll About Eyes™ Serum De-Puffing Eye Massage",
    "CliniqueAll About Lips [CAN]",
    "CliniqueAll About Shadow™ Quad 06 Pink Chocolate",
    "CliniqueAll About Skin Liquid Face Soap Oily Skin Formula",
    "CliniqueAlmost Lipstick",
    "CliniqueAlmost Powder Makeup SPF 15 Neutral Fair",
    "CliniqueAnti Blemish Solutions Cleansing Bar For Face And Body",
    "CliniqueAnti Blemish Solutions Cleansing Foam",
    "CliniqueAnti Blemish Solutions Liquid Makeup",
    "CliniqueAnti-Blemish Solutions All-Over Clearing Treatment",
    "CliniqueAnti-Blemish Solutions Clarifying Lotion",
    "CliniqueAnti-Blemish Solutions Cleansing Gel",
    "CliniqueAnti-Blemish Solutions Makeup",
    "CliniqueAnti-Wrinkle Face Cream Spf 30",
    "CliniqueAnti-blemish Solution Cleansing Gel",
    "CliniqueAnti-blemish Solutions All-over Clearing Treatment"
]

# 3. Function to categorize by title
def match_product(title):
    if pd.isna(title):
        return None
    
    # Extract the best match from the list
    best_match, score = process.extractOne(str(title), clinique_products)
    
    # We use a score threshold so completely unrelated titles don't get forced into a product
    # You can lower this to 50 if you want it to be more aggressive at guessing
    if score >= 55: 
        return best_match
    return None

# Apply the mapping to create the new column
print("Categorizing products based on Title...")
df['Product Name'] = df['Title'].apply(match_product)

# 4. Function to clean out irrelevant reviews
relevant_keywords = [
    'skin', 'face', 'cream', 'acne', 'lotion', 'makeup', 'cleanser', 
    'use', 'buy', 'bought', 'reaction', 'mascara', 'foundation', 
    'moisture', 'routine', 'pores', 'breakout', 'dry', 'oily'
]

def is_review_relevant(text):
    if pd.isna(text):
        return False
    
    text_lower = str(text).lower()
    
    # Check for empty or excessively short text
    if len(text_lower.strip()) < 10:
        return False
        
    # Exclude basic irrelevant compliments
    irrelevant_phrases = ['you are gorgeous', 'so beautiful', 'looking cute', 'love you']
    if any(phrase in text_lower for phrase in irrelevant_phrases) and len(text_lower) < 40:
        return False
        
    # If the text mentions actual skincare/makeup keywords, it stays
    if any(keyword in text_lower for keyword in relevant_keywords):
        return True
        
    # If it's a longer, detailed paragraph, it's likely a real review
    if len(text_lower) > 60:
        return True
        
    return False

print("Filtering out irrelevant reviews...")
df_cleaned = df[df['Body'].apply(is_review_relevant)]

# Optional: Drop rows where a product couldn't be matched at all
df_cleaned = df_cleaned.dropna(subset=['Product Name'])

# 5. Export the clean dataset
output_file = 'clinique_reviews_sentiment_ready.csv'
df_cleaned.to_csv(output_file, index=False)
print(f"Done! Cleaned data saved to {output_file}")
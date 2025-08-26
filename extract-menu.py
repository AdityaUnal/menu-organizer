from google import genai
import os
from dotenv import load_dotenv
from lxml import html
import re
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json

load_dotenv()

# === CONFIG ===
TABLE_XPATH = "//*[@id='mw-content-text']/div[1]/table[4]"
SERVICE_ACCOUNT_FILE = os.path.join(os.getcwd(),f"{os.environ.get('GOOGLE-SHEET-JSON')}")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.environ.get("SPREADSHEET-ID")
RANGE = "Sheet1!A:AB"
VALUE_INPUT_OPTION = "RAW"
INSERT_OPTION = "INSERT_ROWS"
client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY')) 

# Setup Google Sheets API client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("sheets", "v4", credentials=credentials)

class UploadMenu:
    FilePath:str
    data:str
    def __init__(self,FilePath):
        self.FilePath = FilePath
        pass
    def extractImage(self,max_retries = 3):
        
        prompt = '''
        You are an expert at extracting and structuring data from images of restaurant menus. I will provide you with images of a menu, and you must return the data in a structured JSON format.

        Here are the specific details and constraints for the JSON output:

        - **Restaurant Details:**
        - `restaurant_name`: Extract the name of the restaurant. If not explicitly mentioned, leave it.
        - `area_id`: A placeholder for an area ID (e.g., "123"). If not explicitly mentioned, leave it.
        - `area_name`: A placeholder for an area name (e.g., "Central City"). If not explicitly mentioned, leave it.

        - **Menu Categories:**
        - `categories`: An array of objects. Each object should represent a menu category.
            - `id`: A unique, numerical ID for each category (e.g., 1, 2, 3).
            - `name`: The name of the category (e.g., "Special Calzone Menu", "Bao", "Dessert").
            - `image_url`: A placeholder for an image URL.
            - `availability`: A boolean value (`true` or `false`). Assume all items are available unless specified otherwise.
            - `rank`: An integer to determine the display order. Use 1, 2, 3, etc. based on the order in the image.

        - **Menu Items:**
        - `items`: An array of objects within each category. Each object should represent a menu item.
            - `name`: The name of the dish (e.g., "Three Cheese Caprese").
            - `description`: The description of the dish, including ingredients (e.g., "Mozzarella+Cheddar+Cream Cheese +Tomato+Basil+Balsamic Drizzle").
            - `price`: The numerical price of the item.
            - `rank`: An integer to determine the display order within the category.
            - `image_url`: A placeholder for an image URL.
            - `stock_status`: A string. Assume "In Stock" unless a clear indication of being out of stock is present (e.g., a "sold out" icon).

        - **Customizations:**
        - `customizations`: An array of objects. This should only be used for items with add-ons or variations.
            - `group_id`: A unique ID for the customization group.
            - `group_name`: The name of the group (e.g., "Add On").
            - `min_selection`: The minimum number of selections allowed.
            - `max_selection`: The maximum number of selections allowed.
            - `variations`: An array of objects for each customization option.
            - `name`: The name of the variation (e.g., "Gochujang Chicken").
            - `price`: The price of the variation.

        **Important Instructions:**
        - Carefully analyze the menu images to extract all relevant data.
        - Ensure the JSON is properly formatted with correct syntax (commas, brackets, etc.).
        - Use placeholders for `image_url`, `restaurant_name`, `area_id`, and `area_name` as you will not be able to generate these from the image.
        - Pay close attention to items with multiple prices or add-ons and structure them correctly. For items like the "Mexican Style" Calzone, which has two prices, create two separate item entries. The first entry should have the first price, and the second should have the second price with a note in the description (e.g., "Paneer or Chicken"). Similarly, for the "Korean Garlic Buns," create a customization group for the "Add On" options.

        Return only the final JSON object. Do not include any additional text, explanations, or conversational fillers in your response.'''

        uploaded_file = client.files.upload(file = self.FilePath)
        attempt = 0
        while attempt < max_retries:
            try:
                uploaded_file = client.files.upload(file=self.FilePath)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[prompt, uploaded_file]
                )
                
                lines = response.text.splitlines()
                # Strip triple backticks if present
                if lines and lines[0].strip().startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]

                self.data = "\n".join(lines)
                return 200

            except Exception as e:
                wait_time = 2 ** attempt  # exponential backoff: 1, 2, 4...
                print(f"[extractImage] Attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1

        print("[extractImage] Max retries reached, giving up.")
        self.data = ""
        return 500


    def flatten_menu(self):
        if not self.data:
            print("[flatten_menu] No data to flatten.")
            return []

        try:
            json_data = json.loads(self.data)
        except json.JSONDecodeError:
            print("[flatten_menu] Invalid JSON data.")
            return []

        rows = []
        restaurant_name = json_data.get("restaurant_name", "Not Present")
        area_id = json_data.get("area_id", "Not Present")
        area_name = json_data.get("area_name", "Not Present")

        for category in json_data.get("categories", []):
            category_id = category.get("id", "Not Present")
            category_name = category.get("name", "Not Present")
            category_image_url = category.get("image_url", "Not Present")
            category_rank = category.get("rank", "Not Present")
            category_availability = category.get("availability", "Not Present")

            if not category.get("items"):
                continue  # Skip empty categories

            for item in category.get("items", []):
                row = [
                    restaurant_name,
                    area_id,
                    area_name,
                    category_id,
                    category_name,
                    category_image_url,
                    category_availability,
                    category_rank,
                    item.get("id", "Not Present"),
                    item.get("name", "Not Present"),
                    item.get("description", "Not Present"),
                    item.get("price", "Not Present"),
                    item.get("rank", "Not Present"),
                    category_id,
                    item.get("image_url", "Not Present"),
                    item.get("stock_status", "In Stock"),
                ]

                # Optional fields
                optional_fields = [
                    "variation_item_id",
                    "variation_id",
                    "variation_name",
                    "variation_price",
                    "addon_name",
                    "addon_item_selection",
                    "addon_item_selection_min",
                    "addon_item_selection_max",
                    "addon_price",
                    "addon_id",
                    "addon_group_id",
                    "addon_group_name",
                ]
                for field in optional_fields:
                    row.append(item.get(field, "Not Present"))

                rows.append(row)

        return rows

    
    def append_to_sheets(self,max_retries=3):
        values = self.flatten_menu()
        body = {"majorDimension": "ROWS", "values": values}
        attempt = 0
        while attempt < max_retries:
            try:
                result = service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGE,
                    valueInputOption=VALUE_INPUT_OPTION,
                    insertDataOption=INSERT_OPTION,
                    body=body
                ).execute()
                return 200

            except HttpError as e:
                status = e.resp.status
                try:
                    error_content = json.loads(e.content.decode("utf-8"))
                    error_message = error_content.get("error", {}).get("message", "")
                    error_reason = (
                        error_content.get("error", {})
                        .get("errors", [{}])[0]
                        .get("reason", "")
                    )
                except Exception:
                    error_message = str(e)
                    error_reason = ""

                print(f"[Error {status}] {error_message} (reason: {error_reason})")

                if status in (401, 403, 404):
                    # Unrecoverable errors
                    print("Stopping due to unrecoverable error.")
                    return None

                elif status in (429, 500, 503):
                    # Retry with exponential backoff
                    retry_after = int(e.resp.get("Retry-After", "5"))
                    wait_time = retry_after * (2 ** attempt)
                    print(f"{status} → waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                else:
                    print(f"Unrecoverable error {status}. Full response: {e.content}")
                    return None

        print("Max retries reached, giving up.")
        return None

def main():
    for i in range(2):
        print(i)
        obj = UploadMenu(f'data\\task_menu_{i+1}.png')
        if obj.extractImage() == 200:
            print(f"task_menu_{i+1}.png extracted successfully!")
        else:
            print(f"Failed to extract menu. Status code: {status}")
            break
        status = obj.append_to_sheets()
        if status == 200:
            print(f"task_menu_{i+1}.png appended successfully!")
        else:
            print(f"Failed to append menu. Status code: {status}")

if __name__=="__main__":
    main()
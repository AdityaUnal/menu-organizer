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
    def __init__(self,FilePath):
        self.FilePath = FilePath
        pass
    def extractImage(self, category_name,category_id ,max_retries = 3):
        
        prompt = f'''
        You are an expert at extracting and structuring data from images of restaurant menus.

        TASK
        - From the provided menu images, extract ONLY the items that belong to the category named: "{category_name}".
        - If the menu uses a near-synonym or plural/singular variant of the category (e.g., "Burger" vs "Burgers"), treat it as the same category.
        - Do NOT invent items. If none match, return an empty items array.

        OUTPUT FORMAT
        Return a single JSON object with this shape, with the item_category_id have shared (and no extra text):

        {{
        "items": [
            {{
            "itemid": "",                       // leave empty for new items
            "itemallowvariation": "0"|"1",      // "1" if variations are present, else "0"
            "itemname": "<string>",
            "itemrank": "<integer as string>",  // 1-based order; read top-to-bottom, left-to-right within the category
            "item_categoryid": "{category_id}", // leave "" if unknown
            "price": "<numeric as string>",     // e.g., "140"; strip currency symbols and punctuation
            "active": "1",                      // default "1"
            "item_favorite": "0",               // default "0"
            "itemallowaddon": "0"|"1",          // "1" if add-ons are present, else "0"
            "itemaddonbasedon": "0",            // default "0" (add-ons not tied to variation)
            "instock": "2",                     // default "2" (in stock); use "0" if clearly sold out
            "ignore_taxes": "0",                // default "0"
            "ignore_discounts": "0",            // default "0"
            "days": "-1",                       // default "-1"
            "item_attributeid": "",             // unknown => empty string
            "itemdescription": "<string>",      // concise description; join bullet points with ", "
            "minimumpreparationtime": "",       // unknown => empty string
            "item_image_url": "",               // placeholder
            "variation": [
                // present only when itemallowvariation == "1"
                {{ "name": "<string>", "price": "<numeric as string>" }}
            ],
            "addon": [
                // present only when itemallowaddon == "1"
                {{
                "addon_group_id": "",                 // leave empty if unknown
                "addon_item_selection": "S"|"M",      // "S" = single choice; "M" = multiple allowed
                "addon_item_selection_min": "<int as string>",
                "addon_item_selection_max": "<int as string>"
                }}
            ],
            "item_tax": ""                     // do not invent tax IDs; leave empty if unknown
            }}
        ]
        }}

        EXTRACTION RULES
        1) CATEGORY SCOPING
        - Only include items visually under the heading that matches "{category_name}" or a close lexical variant.
        - If headings are ambiguous, prefer the nearest visible header above the items.

        2) PRICE PARSING
        - Normalize prices to numbers-as-strings (e.g., "₹140/-" → "140").
        - If an item shows multiple sizes/variants with different prices (e.g., "Half 140 / Full 220"):
            • Prefer "variation" entries with name, price and set "itemallowvariation" = "1".
            • If the menu clearly lists the variants as separate named items, create separate items instead.
        - If both a base price and variations exist, set the base price in "price" and also include variations.

        3) RANKING
        - "itemrank" starts at "1" and increments by reading order within the category (top→bottom, left→right).

        4) ADD-ONS / CUSTOMIZATIONS
        - When the menu offers optional extras (e.g., “Add Cheese +30”, “Choose any 2 sauces”):
            • Set "itemallowaddon" = "1".
            • Use "addon_item_selection" = "S" if the text implies “choose 1”; use "M" if “choose any”/“choose up to N”.
            • Set min/max from the text; if unspecified, use min "0" and max "1" for S, or a reasonable observed max for M.
            • Do not invent "addon_group_id"; leave it empty if unknown.
        - Do not put add-ons into "variation". Variations are mutually exclusive forms of the item; add-ons are optional extras.

        5) STOCK
        - Default "instock" = "2".
        - If the item or its label clearly indicates unavailability (e.g., “Sold Out”, crossed-out), set "instock" = "0" and keep "active" = "1".

        6) TEXT CLEANUP
        - Preserve exact item names when possible; remove obvious OCR artifacts.
        - "itemdescription": concise, readable sentence/phrase. Include notable ingredients or style cues from the image.

        7) SAFETY & HALLUCINATION
        - Do NOT guess tax IDs, attribute IDs, prep time, or group IDs; leave those fields empty if not visible.
        - Do NOT add categories or items not present in the image.
        - Do NOT add decorative sections, marketing blurbs, or explanations (e.g., “What’s a Calzone”). Only extract actual menu items under category headings.

        RETURN FORMAT
        - Return only the final JSON object as specified above. No prose, no Markdown, no explanations.
    '''

        uploaded_file = client.files.upload(file = self.FilePath)
        attempt = 0
        while attempt < max_retries:
            try:
                uploaded_file = client.files.upload(file=self.FilePath)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[prompt, uploaded_file]
                )
                
                new_items = response.text
                # Strip triple backticks if present
                new_items = new_items.strip().removeprefix("```json").removesuffix("```").strip()

                return new_items

            except Exception as e:
                wait_time = 2 ** attempt  # exponential backoff: 1, 2, 4...
                print(f"[extractImage] Attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1

        print("[extractImage] Max retries reached, giving up.")

        return ""

        
def flatten_menu(json_data):
    rows = []

    # restaurant info
    restaurant_name = json_data["restaurants"][0]["details"]["restaurantname"]

    # pick first area (or mark Not Present)
    areas = json_data.get("areas", [])
    area_id = areas[0]["areaid"] if areas else "Not Present"
    area_name = areas[0]["displayname"] if areas else "Not Present"

    # category lookup
    category_lookup = {c["categoryid"]: c for c in json_data.get("categories", [])}

    for item in json_data.get("items", []):
        cat = category_lookup.get(item.get("item_categoryid"), {})

        base_row = [
            restaurant_name,                                # restaurant_name
            area_id,                                        # area_id
            area_name,                                      # area_display_name
            cat.get("categoryid", "Not Present"),           # category_id
            cat.get("categoryname", "Not Present"),         # category_name
            cat.get("category_image_url", "Not Present"),   # category_image_url
            cat.get("categorytimings", "Not Present"),      # category_timings
            cat.get("categoryrank", "Not Present"),         # category_rank
            item.get("itemid", "Not Present"),              # item_id
            item.get("itemname", "Not Present"),            # item_name
            item.get("itemdescription", "Not Present"),     # item_description
            item.get("price", "Not Present"),               # price
            item.get("itemrank", "Not Present"),            # rank
            cat.get("categoryid", "Not Present"),           # category_id (repeat)
            item.get("item_image_url", "Not Present"),      # image_url
            item.get("instock", "Not Present"),             # instock
        ]

        # === Case 1: No variation ===
        if not item.get("variation"):
            if not item.get("addon"):
                row = base_row + [
                    "Not Present",  # variation_item_id
                    "Not Present",  # variation_id
                    "Not Present",  # variation_name
                    "Not Present",  # variation_price
                    "Not Present",  # addon_name
                    "Not Present",  # addon_item_selection
                    "Not Present",  # addon_item_selection_min
                    "Not Present",  # addon_item_selection_max
                    "Not Present",  # addon_price
                    "Not Present",  # addon_id
                    "Not Present",  # addon_group_id
                    "Not Present",  # addon_group_name
                ]
                rows.append(row)
            else:
                for addon in item["addon"]:
                    row = base_row + [
                        "Not Present",                          # variation_item_id
                        "Not Present",                          # variation_id
                        "Not Present",                          # variation_name
                        "Not Present",                          # variation_price
                        "Not Present",                          # addon_name (not in JSON)
                        addon.get("addon_item_selection", "Not Present"),
                        addon.get("addon_item_selection_min", "Not Present"),
                        addon.get("addon_item_selection_max", "Not Present"),
                        "Not Present",                          # addon_price
                        "Not Present",                          # addon_id
                        addon.get("addon_group_id", "Not Present"),
                        "Not Present",                          # addon_group_name
                    ]
                    rows.append(row)

        # === Case 2: With variations ===
        else:
            for variation in item["variation"]:
                var_base = base_row + [
                    variation.get("id", "Not Present"),         # variation_item_id
                    variation.get("variationid", "Not Present"),# variation_id
                    variation.get("name", "Not Present"),       # variation_name
                    variation.get("price", "Not Present"),      # variation_price
                ]

                if variation.get("addon"):
                    for addon in variation["addon"]:
                        row = var_base + [
                            "Not Present",                          # addon_name
                            addon.get("addon_item_selection", "Not Present"),
                            addon.get("addon_item_selection_min", "Not Present"),
                            addon.get("addon_item_selection_max", "Not Present"),
                            "Not Present",                          # addon_price
                            "Not Present",                          # addon_id
                            addon.get("addon_group_id", "Not Present"),
                            "Not Present",                          # addon_group_name
                        ]
                        rows.append(row)
                else:
                    row = var_base + [
                        "Not Present",  # addon_name
                        "Not Present",  # addon_item_selection
                        "Not Present",  # addon_item_selection_min
                        "Not Present",  # addon_item_selection_max
                        "Not Present",  # addon_price
                        "Not Present",  # addon_id
                        "Not Present",  # addon_group_id
                        "Not Present",  # addon_group_name
                    ]
                    rows.append(row)


    return rows



    
def append_to_sheets(data,max_retries=3):
    values = flatten_menu(data)
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

def extract_menu_json(FilePath):
    try:
        with open(FilePath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        # Re-shape into the same structure extractImage() would return
        # so flatten_menu() works without changes
        return raw_data
    
    except Exception as e:
        print(f"[extract_menu_json] Failed: {e}")
        return " "

def main():
    data = extract_menu_json('data\\data_reference.json')
    for i in range(2):
        print(i)
        obj = UploadMenu(f'data\\task_menu_{i+1}.png')
        for category in data["categories"]:
            category_name = category['categoryname']
            category_id = category['categoryid']
            new_items = obj.extractImage(category_name=category_name,category_id=category_id)
            if len(new_items) == 0:
                continue
            new_items = json.loads(new_items)
            print(f"Extracted {len(new_items["items"])} in category of {category_name}")
            if len(new_items["items"]) != 0 :
                data["items"].extend(new_items["items"])

    append_status = append_to_sheets(data)
    if append_status==200:
        print("Appended Successfully")

    else:
        print("Could not append")
        

if __name__=="__main__":
    main()
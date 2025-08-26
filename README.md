# Menu-Organizer

- I have created a menu extarctor which uses gemini apis to extract the data into a json.
- I tried to look into some ML models that I can fine tune myself, but it would take a lot more time, and I cannot really gurantee accuracy on that. 
- A **Small Language Model**, finetuned for menus may be optimal here. 

## Getting Started
- Setup the google cloud developer account and project for allowing to edit google sheet([Steps](https://ai2.appinventor.mit.edu/reference/other/googlesheets-api-setup.html))
- Download the json and save it as menu-organizer.json
- Type the following commands in the terminal :
```code
git clone https://github.com/AdityaUnal/menu-organizer
pip install -r requirements.txt
python extract-menu.py
```
- The .env file should look like this :
```
GEMINI_API_KEY=xxxx
GOOGLE-SHEET-JSON=menu-organizer.json
SPREADSHEET-ID=xxxx
```
## Key points
- I have sent rows of one menu at once to the google sheet as the payload size is less here and google APIs allow upto 2 MB of data in one payload.
- Google Sheets allows up to 300 writes per minute; batching ensures scalability for larger menus.
- I tried a lot to use OCR + custom LLM pipeline. For this image preprocessing and postprocessing was required. These images can be seen in data and temp folder. 
- Ultimatley I went with using LLMs, as it felt much more simpler and accurate.
- The check.ipynb and extract-menu.ipynb are like rough notebooks where I tried the approaches.
- The excel sheet can be find [here](https://docs.google.com/spreadsheets/d/13BMAJ7pufqLy_wiDEn33anfJqMOh0vOt9_K2qWygneI/edit?usp=sharing).

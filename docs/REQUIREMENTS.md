1. MVP
=========
  - 2 applications
    1. mobile application (focus on Android) 
    2. Backend running on my linux server to collect all data and do post-processing


  1. Mobile application
  - Title of application: `Copywaste Notes`. 
  - User can start recording a voice note with press of 1 button
  - User is able to start recording from the phone desktop (maybe using a desktop widget in Android?)
  - Once recording: 'start recording' button changes to 'stop recording' button. When it is clicked, it stops recording audio.
  - Once recording is done, the audiofile gets transmitted to the backend application
  - each note will have a 'status' field, initially always set to 'Open'. Other states can be: 'In Progress', 'Todo', 'Closed'.
  - The app receives a list of all notes from the backend and shows them in a table-view with the following fields: creation time, summary/title, duration of recording, status of note 
  - User is able to change the status of a note easily from the table-view.
  - User is able to edit the Markdown that contains the initial transcript and the changes get saved in the backend. 
  - User can determine which 'status' values are going to be filtered in the list from the settings menu.



  2. Backend
  - Receives audiofiles. For each audiofile, it generates a text transcript and saves that transcript in a markdown together with a link to the original audiofile.
  - For each transcript, also a text summary gets created which can function as a title for the note. 
  - the backend can serve a list of all the received notes and is able to present that list sorted on several fields: creation time, duration of recording, status of the note

2. Phase 2
==========
### 2.1 Date/Time recognition
  #### 2.1.1. Google Calendar link
  Make it possible for the user to link their Google Calendar to the backend. We want the backend to recognize dates/times and schedule an event in the google calendar. Use the Python `dateparser` library for parsing dates.
  #### 2.1.2. Extra Datetime field
  When the backend recognizes a date/time, it also creates a new Datetime field `scheduledAt`. 

3. Phase 3
==========
### 3.1 Make the app and backend Multi-user
Log into the app using your Google account. Make sure the backend saves all data linked to that user. 
Also use that same login to link to Google Calendar. 

### 3.2 New HTML frontend
Now we want to have the same functionality as is in the Android app, but this time using only html and vanilla javascript. If partial page updates are necessary, use HTMX and serverside rendering on the backend for this. 
Also use Google account to log into the frontend.
Make sure this HTML-frontend is mobile-friendly.
This should all be deployed to https://notes.copywaste.org
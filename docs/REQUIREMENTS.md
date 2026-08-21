- 2 applications
  1. mobile application (focus on Android) 
  2. Backend running on my linux server to collect all data and do post-processing


1. Mobile application
- Title of application: `cjpa's Notes`. 
- User can start recording a voice note with press of 1 button
- User is able to start recording from the phone desktop (maybe using a desktop widget in Android?)
- Once recording: 'start recording' button changes to 'stop recording' button. When it is clicked, it stops recording audio.
- Once recording is done, the audiofile gets transmitted to the backend application
- each note will have a 'status' field, initially always set to 'Open'. Other states can be: 'In Progress', 'Todo', 'Closed'.
- The app receives a list of all notes from the backend and shows them in a table-view with the following fields: creation time, summary/title, duration of recording, status of note 
- User is able to change the status of a note easily from the table-view.
- User is able to edit the Markdown that contains the initial transcript and the changes get saved in the backend. 


2. Backend
- Receives audiofiles. For each audiofile, it generates a text transcript and saves that transcript in a markdown together with a link to the original audiofile.
- For each transcript, also a text summary gets created which can function as a title for the note. 
- the backend can serve a list of all the received notes and is able to present that list sorted on several fields: creation time, duration of recording, status of the note


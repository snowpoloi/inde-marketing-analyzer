# Ρύθμιση Gmail για info@inde.gr

Η σύνδεση Gmail στο Codex δεν εξουσιοδοτεί τον Coolify server. Χρειάζεται ξεχωριστή OAuth εφαρμογή μόνο για την ανάγνωση των εγγράφων της MEGAPAP. Δεν χρειάζεται κωδικός Gmail, app password ή αλλαγή στο email.

## 1. Google Cloud

1. Άνοιξε το [Google Cloud Console](https://console.cloud.google.com/) με τον λογαριασμό που διαχειρίζεται το Workspace της INDE και δημιούργησε ξεχωριστό project, π.χ. `INDE Supplier Readonly`.
2. Στο **APIs & Services → Library**, ενεργοποίησε το **Gmail API**.
3. Στο **Google Auth Platform → Branding**, βάλε όνομα `INDE Supplier Readonly`, email υποστήριξης `info@inde.gr` και τα πραγματικά εταιρικά στοιχεία.
4. Στο **Audience**, επίλεξε **Internal** αν το project ανήκει στο Google Workspace της INDE. Αν δεν είναι διαθέσιμο, επίλεξε **External** και πρόσθεσε μόνο το `info@inde.gr` στους test users για την πρώτη δοκιμή.
5. Στο **Data Access**, ζήτησε μόνο `https://www.googleapis.com/auth/gmail.readonly`. Όχι `gmail.modify`, `gmail.send`, `mail.google.com` ή δικαιώματα Drive.
6. Στο **Clients → Create client**, επίλεξε **Desktop app**, όνομα `INDE Supplier Local Authorization`. Κατέβασε το client JSON σε ιδιωτικό φάκελο **έξω από το project**, π.χ. `C:\Users\snowp\Documents\Codex\credentials\supplier-client.json`.

Το Desktop client χρησιμοποιείται μία φορά στον υπολογιστή σου για συγκατάθεση, με τοπικό callback. Δεν βάζουμε το δημόσιο URL της εφαρμογής ως callback και δεν εκθέτουμε OAuth σελίδα στον server. Δες τις επίσημες οδηγίες [Google Gmail Python setup](https://developers.google.com/workspace/gmail/api/quickstart/python) και [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).

**Προσοχή στο External / Testing:** για Gmail scope, το refresh token σε αυτό το καθεστώς συνήθως λήγει σε 7 ημέρες. Δεν είναι κατάλληλο για μόνιμη παραγωγική σύνδεση. Για εταιρικό Workspace προτίμησε Internal. Διαφορετικά έλεγξε τις απαιτήσεις Publishing/Verification της Google πριν ενεργοποιήσεις μόνιμη λειτουργία. Το ότι επιλέξαμε read-only δεν παρακάμπτει τις απαιτήσεις verification του restricted Gmail scope. [Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## 2. Μία τοπική εξουσιοδότηση

Από τον φάκελο του project, με τις βιβλιοθήκες του `backend/requirements-dev.txt` εγκατεστημένες:

```powershell
& .\.venv\Scripts\python.exe backend\scripts\authorize_supplier_gmail.py --client "C:\Users\snowp\Documents\Codex\credentials\supplier-client.json" --output "C:\Users\snowp\Documents\Codex\credentials\supplier-gmail.env"
```

Δημιούργησε πρώτα τον ιδιωτικό φάκελο `credentials`. Το output πρέπει να είναι νέο αρχείο, έξω από το repository. Θα ανοίξει το Google consent στον browser. Επίλεξε **αποκλειστικά `info@inde.gr`** και επιβεβαίωσε πρόσβαση ανάγνωσης. Αν υπάρχει Workspace περιορισμός εφαρμογών, ο διαχειριστής πρέπει να εγκρίνει αυτόν τον συγκεκριμένο client και scope.

Το βοηθητικό εργαλείο ελέγχει τον λογαριασμό, τον client και τα πραγματικά granted scopes πριν δημιουργήσει το αρχείο. Δεν εμφανίζει tokens στο terminal. Μην ανεβάσεις το JSON ή το `.env` στο GitHub, μην τα επισυνάψεις εδώ και μην τα βάλεις σε κοινόχρηστο φάκελο. Τα Windows δικαιώματα πρόσβασης του ιδιωτικού φακέλου πρέπει να περιορίζονται στον δικό σου λογαριασμό.

## 3. Coolify

Στο resource της εφαρμογής → **Environment Variables**, πέρασε ιδιωτικά τις τέσσερις τιμές από το αρχείο:

```dotenv
SUPPLIER_GMAIL_ENABLED=true
SUPPLIER_GMAIL_CLIENT_ID=<τιμή από το ιδιωτικό αρχείο>
SUPPLIER_GMAIL_CLIENT_SECRET=<τιμή από το ιδιωτικό αρχείο>
SUPPLIER_GMAIL_REFRESH_TOKEN=<τιμή από το ιδιωτικό αρχείο>
```

Χρειάζονται στο **runtime του backend και worker**, όχι ως build variables ούτε στο frontend. Κάνε redeploy. Αν αποτύχει η εξουσιοδότηση, η εφαρμογή σταματά χωρίς να διαβάσει μηνύματα άλλου λογαριασμού.

## 4. Πρώτη χρήση

**Suppliers & COGS → Gmail documents**. Η αυτόματη ανάγνωση ενεργοποιείται όταν υπάρχουν τα dedicated credentials. Ελέγχει κάθε 15 λεπτά, αρχικά τις τελευταίες 30 ημέρες και μετά με επικάλυψη 2 ημερών. Ο worker διαβάζει έως 10 μηνύματα ανά βήμα, συνεχίζει μόνος του τις σελίδες και κρατά checkpoints στη βάση ακόμη και μετά από restart. Μόνο MEGAPAP αποστολείς ή προωθημένα μηνύματα από `info@inde.gr` που αναφέρουν MEGAPAP περιλαμβάνονται στην αναζήτηση.

Για παλαιότερη περίοδο επίλεξε έως 90 ημέρες και πάτησε **Read Gmail**: επιστρέφει άμεσα queued και η ανάγνωση συνεχίζεται στον worker, χωρίς ανοιχτό browser. Η καρτέλα ενημερώνει κατάσταση, σελίδες, μηνύματα, skipped και έγγραφα κάθε 15 δευτερόλεπτα. Τα ίδια μηνύματα/έγγραφα δεν γίνονται δεύτερη οικονομική εγγραφή. Προσωρινές αποτυχίες επαναλαμβάνονται με καθυστέρηση έως 3 φορές· η πρόοδος κάθε ολοκληρωμένου μηνύματος διατηρείται.

Προαιρετικές runtime ρυθμίσεις και για backend και για worker: `SUPPLIER_GMAIL_AUTO_ENABLED=false` σταματά μόνο τις αυτόματες νέες εργασίες, ενώ `SUPPLIER_GMAIL_INTERVAL_MINUTES=15` ορίζει διάστημα 5 έως 1440 λεπτών. Το `SUPPLIER_GMAIL_ENABLED=false` σταματά όλες τις αναγνώσεις, συμπεριλαμβανομένων των queued εργασιών.

Τα υποστηριζόμενα text PDFs και HTML σώματα αποθηκεύονται πρώτα ως pending. Έλεγξε το έγγραφο, τις γραμμές, ποσότητες, SKU και ποσά. Επιβεβαίωσε ότι πρόκειται για παραγγελία προμηθευτή και συμπλήρωσε **πραγματική καθαρή αξία και ΦΠΑ των μεταφορικών** πριν αποδεχτείς το cost evidence. Μη θεωρήσεις τον προσωρινό μηδενικό ΦΠΑ μεταφορικών επιβεβαιωμένη απαλλαγή.

Αν έχεις δωρεάν μεταφορικά και ο προμηθευτής αφαιρεί τη χρέωση στην τιμολόγηση, επίλεξε **Free shipping - supplier removes freight at invoicing** για το συγκεκριμένο έγγραφο. Η αποδοχή αποθηκεύει μηδενικά μεταφορικά/ΦΠΑ μεταφορικών και αφαιρεί το εμφανιζόμενο freight από το σύνολο κόστους, χωρίς αλλαγή στις τιμές ή στον ΦΠΑ προϊόντων. Το αρχικό email payload παραμένει αμετάβλητο. Το αποδεκτό cost evidence κρατά το αρχικό σύνολο, την αρχική χρέωση και ποιος/πότε επιβεβαίωσε τη μηδενική χρέωση. Δεν εφαρμόζεται αυτόματη απαλλαγή σε άλλα έγγραφα ούτε τροποποιείται φορολογικό τιμολόγιο.

Μη αναγνωρίσιμο PDF ή αλλαγή layout μένει στο review. Άγνωστο προϊόν εμφανίζεται στα **Unmatched products** με έγγραφο, κόστος, υποψήφια προϊόντα και αιτία. Η χειροκίνητα επιβεβαιωμένη αντιστοίχιση αποθηκεύεται για επόμενα έγγραφα.

## Όρια ασφαλείας

- Η Google κίνηση Gmail είναι μόνο GET: profile, λίστα μηνυμάτων, μήνυμα, attachment. Μόνο το OAuth refresh χρησιμοποιεί POST, όχι αποστολή email.
- Δεν υπάρχουν send/delete/modify/labels/archive/mark endpoints. Ο server απορρίπτει tokens με ευρύτερα scopes και κάθε mailbox εκτός `info@inde.gr`.
- Pending/rejected/unsupported έγγραφα δεν παράγουν οικονομικές εγγραφές. Τα αποδεκτά supplier orders δίνουν ιστορικό κόστος αλλά **δεν μετρώνται ως φορολογικές αγορές/τιμολόγια**.
- Τα μεταφορικά παραμένουν χωριστά από το Product Margin. Τα duplicates ελέγχονται με immutable IDs, hashes περιεχομένου, normalized identity και τον υπάρχοντα financial importer.
- Η αυτόματη ανάγνωση κάνει μόνο staging, ποτέ οικονομική αποδοχή. Δεν προστέθηκε άλλος supplier ή XML feed.

Ανάκληση: βάλε `SUPPLIER_GMAIL_ENABLED=false`, κάνε redeploy και ανακάλεσε τη συγκεκριμένη εφαρμογή από τον Google λογαριασμό. Η απενεργοποίηση δεν διαγράφει το ήδη αποθηκευμένο τοπικό ιστορικό.

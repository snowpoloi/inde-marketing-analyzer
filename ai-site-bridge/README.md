# AI Site Bridge

**Σχεδίασε με AI builder — διαχειρίσου με WordPress.**

Το AI Site Bridge είναι ένα WordPress plugin που παίρνει sites φτιαγμένα σε AI builders
(Lovable, Bolt, v0, Emergent κ.ά.), τα εισάγει μέσα στο WordPress και από εκεί σου δίνει
πλήρη διαχείριση για **περιεχόμενο, SEO, πολυγλωσσία και WooCommerce** — χωρίς να
αγγίξεις ξανά κώδικα και χωρίς δεύτερο hosting.

```
AI builder (design)  ──GitHub──▶  AI Site Bridge  ──▶  WordPress (διαχείριση)
     Lovable / Bolt / v0              import              SEO · Μεταφράσεις ·
                                                          WooCommerce · Περιεχόμενο
```

## Πώς δουλεύει

1. **Σχεδιάζεις** το site στον AI builder. Ο builder συγχρονίζει τον κώδικα σε GitHub repo.
2. Το bundled GitHub Action (`templates/aisb-build.yml`) **κάνει build** το site και
   δημοσιεύει τα στατικά αρχεία στο branch `aisb-build` σε κάθε push.
3. Το plugin **κατεβάζει το build από το GitHub** (κουμπί "Sync now" ή αυτόματα μέσω
   webhook), αναλύει κάθε HTML σελίδα, αντιγράφει τα assets στο `uploads/aisb-site/`
   και δημιουργεί μία WordPress σελίδα ανά HTML αρχείο — με το design 100% ανέπαφο.
4. Ο parser εντοπίζει **κάθε κείμενο και εικόνα** του design και τα βάζει σε κατάλογο
   ώστε να είναι επεξεργάσιμα και μεταφράσιμα από το WP admin.
5. Σε re-sync μετά από αλλαγή του design, **τα edits, οι μεταφράσεις και τα SEO σου
   διατηρούνται** — τα strings έχουν σταθερά κλειδιά βασισμένα στο περιεχόμενό τους.

## Δυνατότητες (MVP)

### GitHub Sync
- Import από οποιοδήποτε repo/branch (public ή private με token).
- Αυτόματος εντοπισμός build φακέλου (`dist`, `build`, `out`) ή χειροκίνητος ορισμός.
- Webhook endpoint (`/wp-json/aisb/v1/sync`) με HMAC υπογραφή GitHub για αυτόματο
  re-import σε κάθε push.

### Περιεχόμενο
- Κάθε κείμενο (τίτλοι, παράγραφοι, κουμπιά) και κάθε εικόνα (URL + alt) γίνεται
  επεξεργάσιμο string στο **Content & SEO**.
- Τα overrides εφαρμόζονται render-time — το αρχικό design μένει άθικτο.

### SEO
- Meta title & description ανά σελίδα (μεταφράσιμα ανά γλώσσα).
- Open Graph tags, canonical, `noindex` ανά σελίδα.
- Πολυγλωσσικό sitemap στο `/aisb-sitemap.xml` με `hreflang` alternates.

### Πολυγλωσσία
- Απεριόριστες γλώσσες με URLs τύπου `/en/…`, `/de/…` (η default χωρίς πρόθεμα).
- Πίνακας μεταφράσεων ανά σελίδα/γλώσσα, `hreflang` tags, `<html lang>`,
  αυτόματο language prefix στα εσωτερικά links, floating language switcher.

### Companion Theme (ολοκληρωμένο look σε όλο το site)
- Με ένα κλικ (**Dashboard → Generate theme**) το plugin παράγει το **AI Site Bridge
  Theme** μέσα στο `wp-content/themes/` από το imported design: ίδιο header, footer,
  γραμματοσειρές, CSS και body classes.
- Έτσι οι σελίδες που σερβίρει το WordPress — **σελίδες προϊόντος, καλάθι, checkout,
  άρθρα blog, αναζήτηση, 404** — δείχνουν σαν φυσική συνέχεια του design σου.
- Τα edits που κάνεις στα κείμενα του header/footer (Content & SEO) εφαρμόζονται
  και στο theme, και το theme **ανανεώνεται αυτόματα σε κάθε design sync**.
- Το ενεργοποιείς από Appearance → Themes· αν δεν θες, οτιδήποτε άλλο theme
  συνεχίζει να δουλεύει κανονικά (οι imported σελίδες το παρακάμπτουν έτσι κι αλλιώς).

### WooCommerce & Blog ζώνες
- Ορίζεις "ζώνες": ένα CSS selector (π.χ. `#products`, `section.shop`) ή marker
  `@name` (στοιχείο με `data-aisb-zone="name"` μέσα στον AI builder).
- Η ζώνη γεμίζει render-time με **πραγματικά προϊόντα WooCommerce** (εικόνα, τιμή,
  add-to-cart) ή **πρόσφατα άρθρα**, με minimal CSS που κληρονομεί γραμματοσειρές
  και χρώματα από το design σου.

## Εγκατάσταση

1. Αντέγραψε τον φάκελο `ai-site-bridge/` στο `wp-content/plugins/` και ενεργοποίησε
   το plugin.
2. Βεβαιώσου ότι τα Permalinks είναι σε "Post name" (Settings → Permalinks → Save).
3. **AI Site Bridge → Settings**: όρισε repo (`owner/name`), branch (`aisb-build`),
   token αν το repo είναι private, και τις γλώσσες σου.
4. Στο repo του AI builder πρόσθεσε το workflow από το
   `templates/aisb-build.yml` ως `.github/workflows/aisb-build.yml`.
5. **AI Site Bridge → Dashboard → Sync now.**

### Σημείωση για SPA builds

Οι περισσότεροι AI builders βγάζουν single-page apps (ένα `index.html`, routes μέσω
JavaScript). Για να εισαχθεί **κάθε** σελίδα ξεχωριστά (απαραίτητο για SEO), πρόσθεσε
prerender στο build — π.χ. `vite-ssg`, `vite-plugin-prerender` ή `react-snap` — ώστε
κάθε route να παράγει δικό της HTML αρχείο. Χωρίς prerender εισάγεται μόνο η αρχική.

## Αρχιτεκτονική

```
ai-site-bridge/
├── ai-site-bridge.php          # Bootstrap
├── includes/
│   ├── class-plugin.php        # CPT, routing, rewrite rules, REST webhook
│   ├── class-activator.php     # Πίνακες DB, defaults
│   ├── class-importer.php      # GitHub download, εντοπισμός build, import
│   ├── class-parser.php        # DOM ανάλυση, string catalog, URL rewriting
│   ├── class-store.php         # Data layer (strings, translations)
│   ├── class-renderer.php      # Front-end render: overrides, langs, zones
│   ├── class-seo.php           # Head injection, sitemap
│   ├── class-zones.php         # WooCommerce/blog ζώνες, selector→XPath
│   ├── class-theme.php         # Companion theme generator + chrome runtime
│   └── class-admin.php         # Admin UI + form handlers
├── admin/css/admin.css
└── templates/aisb-build.yml    # GitHub Action για auto-build
```

- Οι σελίδες αποθηκεύονται ως custom post type `aisb_page` (κρυφό από το UI), με το
  annotated HTML σε post meta.
- Strings/μεταφράσεις σε δύο custom tables (`aisb_strings`, `aisb_translations`).
- Τα κλειδιά των strings είναι deterministic hashes του περιεχομένου, οπότε τα
  re-imports δεν χαλάνε edits/μεταφράσεις.

## Roadmap (επόμενες φάσεις)

- [ ] Import μέσω ZIP upload και URL crawl (χωρίς GitHub).
- [ ] AI auto-translate των strings (Claude API) με ένα κλικ.
- [ ] Visual zone picker (point & click πάνω στο design αντί για CSS selector).
- [ ] Ζώνες cart/checkout με πλήρη Woo blocks integration.
- [ ] JS για mobile menu toggle στο companion theme (τα burger menus των SPA
      builds βασίζονται σε JS που δεν μεταφέρεται στο theme).
- [ ] Μενού του design συνδεδεμένα με WP Menus.
- [ ] Ενσωμάτωση με Rank Math / Yoast αντί για το built-in SEO layer.

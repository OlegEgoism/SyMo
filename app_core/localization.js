import { TRANSLATIONS } from './language.js';

export class Localization {
  constructor(language = 'en') {
    this.setLanguage(language);
  }

  setLanguage(language) {
    this.language = TRANSLATIONS[language] ? language : 'en';
  }

  t(key) {
    return TRANSLATIONS[this.language]?.[key] ?? TRANSLATIONS.en[key] ?? key;
  }
}

// Vite seems not to have functionality to provide globals for embedded libraries, so this is done
// here manually.
// This file contains libraries that are themselves dependent on things to be present in order
// to be imported.

import './globals';
import * as BuildbotDataJs from 'buildbot-data-js';
import * as BuildbotUi from 'buildbot-ui';

declare global {
  /* eslint-disable no-var */
  var BuildbotDataJs: any;
  var BuildbotUi: any;
  /* eslint-enable no-var */
}

window.BuildbotDataJs = BuildbotDataJs;
window.BuildbotUi = BuildbotUi;

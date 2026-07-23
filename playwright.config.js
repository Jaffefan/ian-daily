const fs = require('fs');

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

module.exports = {
  use: {
    launchOptions: fs.existsSync(edge) ? { executablePath: edge } : {},
  },
};

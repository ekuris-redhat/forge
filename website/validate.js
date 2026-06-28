import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const websiteDir = __dirname;
const indexHtmlPath = path.join(websiteDir, 'index.html');
const mainCssPath = path.join(websiteDir, 'src', 'main.css');
const mainJsPath = path.join(websiteDir, 'src', 'main.js');

console.log('--- Starting Frontend Scaffold Validation ---');

// 1. Check file existence
const filesToCheck = [
  { name: 'index.html', path: indexHtmlPath },
  { name: 'src/main.css', path: mainCssPath },
  { name: 'src/main.js', path: mainJsPath }
];

let hasErrors = false;

for (const file of filesToCheck) {
  if (fs.existsSync(file.path)) {
    console.log(`✅ File exists: ${file.name}`);
  } else {
    console.error(`❌ File missing: ${file.name}`);
    hasErrors = true;
  }
}

if (hasErrors) {
  process.exit(1);
}

// 2. Validate index.html contents
const htmlContent = fs.readFileSync(indexHtmlPath, 'utf8');

// Viewport meta check
const hasViewport = htmlContent.includes('<meta name="viewport"');
const hasCorrectScale = htmlContent.includes('width=device-width') && htmlContent.includes('initial-scale=1.0');

if (hasViewport && hasCorrectScale) {
  console.log('✅ Viewport meta tags are set to scale properly');
} else {
  console.error('❌ Missing or incorrect viewport configuration in index.html');
  hasErrors = true;
}

// Global variable usage check (stylesheets linked)
const linksStylesheet = htmlContent.includes('href="/src/main.css"');
if (linksStylesheet) {
  console.log('✅ Global stylesheet link verified in index.html');
} else {
  console.error('❌ Main stylesheet (/src/main.css) not linked in index.html');
  hasErrors = true;
}

// Main JS entrypoint link check
const linksJs = htmlContent.includes('src="/src/main.js"');
if (linksJs) {
  console.log('✅ Main JavaScript entrypoint link verified in index.html');
} else {
  console.error('❌ Main JS (/src/main.js) not linked or not set as module in index.html');
  hasErrors = true;
}

// Charset check
const hasCharset = htmlContent.includes('<meta charset="UTF-8"');
if (hasCharset) {
  console.log('✅ Charset meta tag is set to UTF-8');
} else {
  console.error('❌ Missing UTF-8 charset declaration in index.html');
  hasErrors = true;
}

// 3. Validate main.css contents (CSS variables)
const cssContent = fs.readFileSync(mainCssPath, 'utf8');
const requiredCssVars = [
  '--color-primary',
  '--color-secondary',
  '--color-accent',
  '--font-sans',
  '--font-mono',
  '--spacing-4',
  '--transition-normal'
];

for (const cssVar of requiredCssVars) {
  if (cssContent.includes(cssVar)) {
    console.log(`   - Verified CSS Variable: ${cssVar}`);
  } else {
    console.error(`❌ Missing CSS Variable in main.css: ${cssVar}`);
    hasErrors = true;
  }
}

if (hasErrors) {
  console.error('❌ Validation Failed!');
  process.exit(1);
} else {
  console.log('🎉 All scaffold validation checks passed successfully!');
}

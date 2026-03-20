export function renderDashboardHtml(title) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${title}</title>
    <link rel="stylesheet" href="ui/styles.css" />
  </head>
  <body>
    <main class="dashboard">
      <h1>${title}</h1>
      <div id="metrics" class="metrics"></div>
    </main>
  </body>
</html>`;
}

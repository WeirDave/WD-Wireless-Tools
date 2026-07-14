// Paste into browser console on ekahau.cloud
// Fetches the project API directly and copies the first project's fields to clipboard.

fetch('/projectapi/v1/projects')
  .then(r => r.json())
  .then(data => {
    const projects = Array.isArray(data) ? data : (data.projects || data.items || []);
    if (projects.length > 0) {
      const first = projects[0];
      console.log('%c[WD] First project — all fields:', 'color: #0f0; font-size: 14px');
      console.log(JSON.stringify(first, null, 2));
      console.log('%c[WD] Field names: ' + Object.keys(first).join(', '), 'color: #ff0; font-size: 12px');
      try { copy(JSON.stringify(first, null, 2)); console.log('%c[WD] Copied to clipboard!', 'color: #0f0'); } catch(e) {}
    } else {
      console.log('No projects found');
    }
  })
  .catch(e => console.error('Failed:', e));

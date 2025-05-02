// Function to get the stored URL from browser storage
async function getStoredUrl() {
  try {
    // Use browser.storage which returns a Promise
    const data = await browser.storage.sync.get('websiteUrl');
    return data.websiteUrl || ''; // Return URL or empty string if not set
  } catch (error) {
    console.error("Error getting stored URL:", error);
    return ''; // Return empty string on error
  }
}
// Helper function to shorten and clean the video title
function shortenTitle(title, maxLength = 50) {
  // Remove "- YouTube" suffix if it exists
  const cleanedTitle = title
  .replace(/\s-\sYouTube$/, '')
  .replace(/\(\d+\)\s*/, '')
  .replace(/\./g, '')
  .replace(/\s+/g, ' ')
  .replace(/\([^)]+\)/g, '')
  .replace(/\[[^\]]+\]/g, '')
  .replace(/\,/g, '')
  .replace(/\:/g, '')
  .replace(/\#/g, '')
  .replace(/\|/g, '')
  .replace(/\'/g, '')
  .replace(/\"/g, '')
  .replace(/\?/g, '')
  .trim();
  return cleanedTitle.length > maxLength ? cleanedTitle.slice(0, maxLength) + '' : cleanedTitle;
}

// Load saved website URL, video title, media type, and scene selection on startup
document.addEventListener('DOMContentLoaded', async () => {
  const savedUrl = await getStoredUrl();
  if (savedUrl) {
    document.getElementById('websiteUrl').value = savedUrl;
  }

  // Automatically fetch, clean, and shorten video title on startup
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url.includes("youtube.com")) {
    const shortenedTitle = shortenTitle(tab.title || "Video Title");
    document.getElementById('name').value = shortenedTitle;
  }

  // Initialize the media type and scene dropdowns
  await createMediaTypeDropdown();
  await createSceneDropdown();
});

// Only allow the extension on YouTube pages
browser.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  // Add checks for tab and tab.url existence
  if (!tab || !tab.url || !tab.url.includes("youtube.com")) {
    const alertDiv = document.createElement('div');
    alertDiv.id = 'alert';
    alertDiv.style.position = 'fixed';
    alertDiv.style.top = '0';
    alertDiv.style.left = '0';
    alertDiv.style.width = '100%';
    alertDiv.style.backgroundColor = 'white';
    alertDiv.style.padding = '10px';
    alertDiv.style.border = '1px solid black';
    alertDiv.style.zIndex = '9999';
    alertDiv.textContent = 'This extension only works on YouTube.';
    document.body.appendChild(alertDiv);
    setTimeout(() => {
      alertDiv.remove();
      // Open a new tab to YouTube and close the popup
      browser.tabs.create({ url: 'https://www.youtube.com' }).then(() => {
        window.close();
      }).catch(error => {
        console.error("Error opening YouTube tab:", error);
        window.close(); // Still close popup even if tab creation fails
      });
    }, 2000);
  }
}).catch(error => console.error("Error querying tabs:", error)); // Catch errors during tab query

// Function to save the website URL
document.getElementById('saveUrlButton').addEventListener('click', async () => {
  const websiteUrl = document.getElementById('websiteUrl').value;
  try {
    await browser.storage.sync.set({ websiteUrl });
    console.log('Website URL saved:', websiteUrl);
    alert('Website URL saved successfully!');
  } catch (error) {
    console.error('Error saving Website URL:', error);
    alert('Failed to save Website URL.');
  }
});
// Function to create or refresh the scene dropdown and load saved selection
async function createSceneDropdown() {
  const websiteUrl = await getStoredUrl();
  if (!websiteUrl) {
    console.error('No website URL found in storage.');
    return;
  }

  const url = `${websiteUrl}/api/scenes`;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    const scenes = data.data; // Assuming API returns { data: [...] }
    const parentElement = document.getElementById('dropdownContainer');
    if (!parentElement) {
      console.error('Dropdown container not found!');
      return;
    }

    let dropdown = document.getElementById('sceneDropdown');
    if (!dropdown) {
      dropdown = document.createElement('select');
      dropdown.id = 'sceneDropdown';
      parentElement.appendChild(dropdown);
    } else {
      dropdown.innerHTML = ''; // Clear existing options before repopulating
    }

    for (const scene of scenes) {
      const option = document.createElement('option');
      option.value = scene.scene_ID;
      option.textContent = scene.sceneName;
      dropdown.appendChild(option);
    }

    // Load saved scene selection using browser.storage
    const storageData = await browser.storage.sync.get('sceneId');
    const savedSceneId = storageData.sceneId || '';
    if (savedSceneId) {
      dropdown.value = savedSceneId;
    }

    // Save scene selection on change
    dropdown.addEventListener('change', async () => {
      try {
        await browser.storage.sync.set({ sceneId: dropdown.value });
        console.log('Scene selection saved:', dropdown.value);
      } catch (error) {
        console.error('Error saving scene selection:', error);
      }
    });
  } catch (error) {
    console.error('Error fetching or processing scenes:', error);
  }
}

// Function to create media type dropdown with mp3 and mp4 options and load saved selection
async function createMediaTypeDropdown() {
  const mediaTypes = ['mp3', 'mp4'];
  const dropdown = document.createElement('select');
  dropdown.id = 'mediaTypeDropdown';

  const parentElement = document.getElementById('mediaTypeContainer');
  if (!parentElement) {
    console.error('Media type container not found!');
    return;
  }

  for (const type of mediaTypes) {
    const option = document.createElement('option');
    option.value = type;
    option.textContent = type.toUpperCase();
    dropdown.appendChild(option);
  }

  parentElement.appendChild(dropdown);

  // Load saved media type selection from storage
  try {
    const data = await browser.storage.sync.get('mediaType');
    dropdown.value = data.mediaType || 'mp4'; // Default to mp4 if not found
  } catch (error) {
    console.error("Error loading media type:", error);
    dropdown.value = 'mp4'; // Default on error
  }

  // Save media type selection on change
  dropdown.addEventListener('change', async () => {
    try {
      await browser.storage.sync.set({ mediaType: dropdown.value });
      console.log('Media type saved:', dropdown.value);
    } catch (error) {
      console.error('Error saving media type:', error);
    }
  });
}

// Add refresh scenes button functionality
document.getElementById('refreshScenesButton').addEventListener('click', createSceneDropdown);

// Fetch, clean, and shorten video title on demand
document.getElementById('fetchTitleButton').addEventListener('click', async () => {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !tab.url.includes("youtube.com")) {
      alert("Please navigate to a YouTube video page first.");
      return;
  }
  const title = shortenTitle(tab.title || "Video Title");
  document.getElementById('name').value = title;
});

// Share data to /api/ChromeExtensionAddVideo
document.getElementById('shareButton').addEventListener('click', async () => {
  const websiteUrl = await getStoredUrl();
  if (!websiteUrl) {
    alert('Please enter a valid website URL.');
    return;
  }

  const statusMessage = document.getElementById('status-message');
  statusMessage.textContent = 'Processing...'; // Initial status
  statusMessage.style.backgroundColor = 'lightblue';

  try {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url || !tab.url.includes("youtube.com")) {
        throw new Error("Not on a YouTube page.");
    }

    const match = tab.url.match(/v=([^&]+)/);
    if (!match || !match[1]) {
      throw new Error("Could not extract video ID from the URL.");
    }
    const videoId = match[1];
    const youtubeUrl = `https://www.youtube.com/watch?v=${videoId}`;

    const sceneDropdown = document.getElementById('sceneDropdown');
    const scene_ID = sceneDropdown ? sceneDropdown.value : '';
    const mediaTypeDropdown = document.getElementById('mediaTypeDropdown');
    const mediaType = mediaTypeDropdown ? mediaTypeDropdown.value : '';
    const flname = document.getElementById('name').value;

    if (!flname) {
        throw new Error("Video name cannot be empty.");
    }
    if (!scene_ID) {
        throw new Error("Please select a scene.");
    }

    const data = {
      url: youtubeUrl,
      flname,
      mediaType,
      scene_ID
    };

    const response = await fetch(`${websiteUrl}/api/ChromeExtensionAddVideo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    const result = await response.json(); // Assuming the API returns JSON

    if (!response.ok) {
        // Try to get error message from API response, otherwise use status text
        const errorDetail = result?.message || result?.error || response.statusText;
        throw new Error(`API Error: ${response.status} - ${errorDetail}`);
    }

    console.log('Data sent successfully:', result);
    statusMessage.style.backgroundColor = 'limegreen';
    statusMessage.textContent = 'Request successful!';

  } catch (error) {
    console.error('Error during share operation:', error);
    statusMessage.style.backgroundColor = 'pink';
    statusMessage.textContent = `Request failed: ${error.message}`;
    // Optionally show an alert as well
    // alert(`Error: ${error.message}`);
  }
});

// Function to get the stored URL from Chrome storage

function getStoredUrl() {
  return new Promise((resolve, reject) => {
    chrome.storage.sync.get('websiteUrl', (data) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(data.websiteUrl || '');
      }
    });
  });
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
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url.includes("youtube.com")) {
    const shortenedTitle = shortenTitle(tab.title || "Video Title");
    document.getElementById('name').value = shortenedTitle;
  }

  // Initialize the media type and scene dropdowns
  await createMediaTypeDropdown();
  await createSceneDropdown();
});

// Only allow the extension on YouTube pages
chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  if (!tab.url.includes("youtube.com")) {
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
      // Open a new tab to YouTube
      chrome.tabs.create({ url: 'https://www.youtube.com' });
      // Close the popup immediately
      window.close();
    }, 2000);
  }
});

// Function to save the website URL
document.getElementById('saveUrlButton').addEventListener('click', () => {
  const websiteUrl = document.getElementById('websiteUrl').value;
  chrome.storage.sync.set({ websiteUrl }, () => {
    console.log('Website URL saved:', websiteUrl);
    alert('Website URL saved successfully!');
  });
});

// Function to create or refresh the scene dropdown and load saved selection
async function createSceneDropdown() {
  const websiteUrl = await getStoredUrl();
  if (!websiteUrl) {
    console.error('No website URL found in storage.');
    return;
  }

  const url = `${websiteUrl}/api/scenes`;
  fetch(url)
    .then(response => response.json())
    .then(async (data) => {
      const scenes = data.data;
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
        dropdown.innerHTML = '';
      }

      for (const scene of scenes) {
        const option = document.createElement('option');
        option.value = scene.scene_ID;
        option.textContent = scene.sceneName;
        dropdown.appendChild(option);
      }

      // Load saved scene selection
      const savedSceneId = await new Promise((resolve) => {
        chrome.storage.sync.get('sceneId', (data) => resolve(data.sceneId || ''));
      });
      if (savedSceneId) {
        dropdown.value = savedSceneId;
      }

      // Save scene selection on change
      dropdown.addEventListener('change', () => {
        chrome.storage.sync.set({ sceneId: dropdown.value }, () => {
          console.log('Scene selection saved:', dropdown.value);
        });
      });
    })
    .catch(error => console.error('Error fetching scenes:', error));
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
  const savedMediaType = await new Promise((resolve) => {
    chrome.storage.sync.get('mediaType', (data) => resolve(data.mediaType || 'mp4'));
  });
  dropdown.value = savedMediaType;

  // Save media type selection on change
  dropdown.addEventListener('change', () => {
    chrome.storage.sync.set({ mediaType: dropdown.value }, () => {
      console.log('Media type saved:', dropdown.value);
    });
  });
}

// Add refresh scenes button functionality
document.getElementById('refreshScenesButton').addEventListener('click', createSceneDropdown);

// Fetch and clean video title on demand
document.getElementById('fetchTitleButton').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
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
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
let videoId; // Declare a variable to store the extracted video ID

try {
  const match = tab.url.match(/v=([^&]+)/);
  if (match) {
    videoId = match[1];
  } else {
    throw new Error("No video ID found in the URL");
  }
} catch (error) {
  alert("Error: " + error.message); // Display an alert with the error message
}

if (videoId) {
  // Use the extracted video ID here (e.g., console.log(videoId))
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = 'https://www.youtube.com/watch?v=' + tab.url.match(/v=([^&]+)/)[1];
  const sceneDropdown = document.getElementById('sceneDropdown');
  const scene_ID = sceneDropdown ? sceneDropdown.value : '';
  const mediaTypeDropdown = document.getElementById('mediaTypeDropdown');
  const mediaType = mediaTypeDropdown ? mediaTypeDropdown.value : '';
  const flname = document.getElementById('name').value;
  const statusMessage = document.getElementById('status-message');

  const data = {
    url,
    flname,
    mediaType,
    scene_ID
  };

  fetch(`${websiteUrl}/api/ChromeExtensionAddVideo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  .then(response => response.json())
  .then(result => {
    console.log('Data sent successfully:', result);
    statusMessage.style.backgroundColor = 'limegreen';
    statusMessage.textContent = 'Request successful!';
  
  })
  .catch(error => console.error('Error sending data:', error));
  statusMessage.style.backgroundColor = 'pink';
  statusMessage.textContent = 'Request failed!';
}
});

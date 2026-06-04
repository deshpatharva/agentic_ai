# Resume Optimization Endpoint

## Endpoint Description

The Resume Optimization endpoint processes a user's resume against a job description and provides real-time optimization suggestions using Server-Sent Events (SSE).

**Endpoint:** `POST /api/optimize`

## Request Format

Send a JSON request with the following structure:

```json
{
  "resume_text": "John Doe\nSoftware Engineer\n...",
  "jd_text": "Job Description:\nWe are looking for a Senior Engineer..."
}
```

**Fields:**
- `resume_text` (string, required): The full text of the user's resume
- `jd_text` (string, required): The job description to optimize against

## Response Format

The endpoint returns a Server-Sent Events (SSE) stream with real-time optimization updates. The response header is `Content-Type: text/event-stream`.

### Event Stream Examples

#### 1. Start Event
Signals the beginning of the optimization process.

```json
event: start
data: {
  "optimization_id": "opt_abc123def456",
  "max_iterations": 3,
  "timestamp": "2026-06-03T10:30:00Z"
}
```

#### 2. Iteration Start Event
Marks the beginning of each optimization iteration.

```json
event: iteration_start
data: {
  "iteration": 1,
  "total_iterations": 3,
  "timestamp": "2026-06-03T10:30:02Z"
}
```

#### 3. Task Complete Event
Indicates completion of a specific optimization task within an iteration.

```json
event: task_complete
data: {
  "task": "keyword_matching",
  "iteration": 1,
  "duration_ms": 1250,
  "timestamp": "2026-06-03T10:30:03Z"
}
```

#### 4. Complete Event (Final Result)
The final event containing the complete optimization results.

```json
event: complete
data: {
  "optimization_id": "opt_abc123def456",
  "status": "success",
  "optimized_resume": "John Doe\nSoftware Engineer with 5+ years experience...",
  "suggestions": [
    {
      "section": "summary",
      "suggestion": "Add specific achievements with metrics",
      "priority": "high"
    },
    {
      "section": "skills",
      "suggestion": "Include more job description keywords",
      "priority": "medium"
    }
  ],
  "match_score": 0.87,
  "timestamp": "2026-06-03T10:32:15Z",
  "total_duration_ms": 135000
}
```

## Frontend Usage Example

Here's how to use the endpoint from a JavaScript frontend:

```javascript
async function optimizeResume(resumeText, jdText) {
  const eventSource = new EventSource('/api/optimize', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      resume_text: resumeText,
      jd_text: jdText
    })
  });

  eventSource.addEventListener('start', (event) => {
    const data = JSON.parse(event.data);
    console.log('Optimization started:', data.optimization_id);
    console.log('Total iterations:', data.max_iterations);
  });

  eventSource.addEventListener('iteration_start', (event) => {
    const data = JSON.parse(event.data);
    console.log(`Iteration ${data.iteration} of ${data.total_iterations}`);
    updateProgressBar(data.iteration, data.total_iterations);
  });

  eventSource.addEventListener('task_complete', (event) => {
    const data = JSON.parse(event.data);
    console.log(`Task "${data.task}" completed in ${data.duration_ms}ms`);
  });

  eventSource.addEventListener('complete', (event) => {
    const data = JSON.parse(event.data);
    console.log('Optimization complete!');
    console.log('Match score:', data.match_score);
    console.log('Optimized resume:', data.optimized_resume);
    console.log('Suggestions:', data.suggestions);
    eventSource.close();
    displayResults(data);
  });

  eventSource.addEventListener('error', (event) => {
    console.error('Error during optimization:', event);
    eventSource.close();
  });
}
```

**Note:** Standard EventSource API does not support POST requests. Use a polyfill or fetch-based EventSource implementation:

```javascript
async function optimizeResume(resumeText, jdText) {
  const response = await fetch('/api/optimize', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      resume_text: resumeText,
      jd_text: jdText
    })
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        const eventType = line.slice(7);
        // Store event type for next data line
        window.currentEventType = eventType;
      } else if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        handleEvent(window.currentEventType, data);
      }
    }
  }
}

function handleEvent(eventType, data) {
  switch (eventType) {
    case 'start':
      console.log('Optimization started:', data.optimization_id);
      break;
    case 'iteration_start':
      updateProgressBar(data.iteration, data.total_iterations);
      break;
    case 'task_complete':
      console.log(`Task "${data.task}" completed in ${data.duration_ms}ms`);
      break;
    case 'complete':
      console.log('Optimization complete!');
      displayResults(data);
      break;
  }
}
```

## Timeout & Long-Running Jobs

The resume optimization process is computationally intensive and typically takes **2-3 minutes** to complete, as it involves:
- Parsing and analyzing the resume text
- Comparing against the job description
- Running multiple optimization iterations
- Generating suggestions and scoring matches

**Important:** Set your client timeout to **5+ minutes** (300,000 milliseconds or longer) to avoid premature connection termination:

```javascript
// Set fetch timeout to 5 minutes
const timeoutPromise = new Promise((_, reject) =>
  setTimeout(() => reject(new Error('Request timeout')), 5 * 60 * 1000)
);

const optimizationPromise = fetch('/api/optimize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ resume_text, jd_text })
});

Promise.race([optimizationPromise, timeoutPromise])
  .catch(error => console.error('Optimization failed:', error));
```

If you need to support longer processing times or want to check on optimization status asynchronously, the `optimization_id` returned in the start event can be used to poll for results via a separate endpoint.

## Error Handling

### Stream Closure

If the SSE stream closes unexpectedly before the `complete` event is received:

1. **Temporary interruption:** The stream may close due to network issues. Implement exponential backoff and retry the request with the same `resume_text` and `jd_text`. The server will start a new optimization process.

2. **Server error:** If a server-side error occurs, you will not receive a `complete` event. The connection will close and an HTTP error status may be returned. Check the response status code and any error details in the last received event.

3. **Client-side handling:**

```javascript
async function optimizeWithRetry(resumeText, jdText, maxRetries = 3) {
  let lastError;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      await optimizeResume(resumeText, jdText);
      return; // Success
    } catch (error) {
      lastError = error;
      console.error(`Attempt ${attempt} failed:`, error.message);
      
      if (attempt < maxRetries) {
        // Exponential backoff: 2s, 4s, 8s
        const delayMs = Math.pow(2, attempt) * 1000;
        console.log(`Retrying in ${delayMs}ms...`);
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
  }

  throw new Error(`Optimization failed after ${maxRetries} attempts: ${lastError.message}`);
}
```

4. **Event stream interruption handling:**

```javascript
const eventSource = new EventSource('/api/optimize');

eventSource.onerror = (event) => {
  if (event.readyState === EventSource.CLOSED) {
    console.error('Connection to optimization stream closed');
    eventSource.close();
    // Implement retry logic or notify user
  }
};
```

Expected HTTP status codes:
- `200`: Stream started successfully
- `400`: Invalid request format (missing or malformed `resume_text` or `jd_text`)
- `500`: Server error during optimization

Always log the last received event data before stream closure to help diagnose issues.

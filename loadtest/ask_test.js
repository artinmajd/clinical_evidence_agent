// k6 load test against the deployed /ask endpoint. The goal isn't just
// throughput numbers - it's to generate enough sustained CPU load on the
// existing 2 pods to push them past the HPA's 50% target long enough to
// actually watch it add pods, then watch it scale back down once the
// load stops. k6 reports p95 latency and request throughput automatically
// in its end-of-run summary - exactly the numbers the project plan asks
// for, with no extra scripting needed.
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 8 },  // ramp up to 8 concurrent virtual users
    { duration: '90s', target: 8 },  // hold steady - the window HPA should react within
    { duration: '20s', target: 0 },  // ramp back down
  ],
};

const URL = 'http://34.55.122.66/ask';

// A few different real questions so requests aren't all hitting the
// exact same cache-friendly path - still cheap, still fast, but more
// representative of varied real traffic than one repeated question.
const QUESTIONS = [
  'What weight loss results were reported for tirzepatide in obesity trials?',
  'What dosage of semaglutide was used in the obesity trials?',
  'What were the primary outcomes measured in phase 3 obesity trials?',
];

export default function () {
  const question = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const payload = JSON.stringify({ question, role: 'clinician' });
  const params = { headers: { 'Content-Type': 'application/json' }, timeout: '30s' };

  const res = http.post(URL, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(1);
}

# Провальные по BFCL трейсы: где судья ошибается

Отсортировано по числу прогонов судьи (из 7), которые приняли трейс как успешный. Категория — моя ручная разметка.

| принято | трейс | ручная категория | тип ошибки BFCL | что не так |
|---|---|---|---|---|
| 7/7 | [pilot_50_0002](pilot_50_0002.md) | `genuine_visible` | empty_turn_model_response | turn0 calls have no tool results; engine never confirmed started |
| 7/7 | [pilot_50_0006](pilot_50_0006.md) | `looks_success` | instance_state_mismatch | all requests answered; no set_navigation, hidden fuel/state differences (borderline) |
| 7/7 | [pilot_50_0012](pilot_50_0012.md) | `genuine_visible` | instance_state_mismatch | startEngine/pressBrake/get_ticket given as text with no tool results |
| 7/7 | [pilot_50_0016](pilot_50_0016.md) | `looks_success` | instance_state_mismatch | all requests visibly done; BFCL diff is hidden doors/brake state |
| 7/7 | [pilot_50_0024](pilot_50_0024.md) | `genuine_visible` | instance_state_mismatch | posted "healthy" though user defined healthy as all tires 32-35 and rear are 30 |
| 7/7 | [pilot_50_0028](pilot_50_0028.md) | `looks_success` | instance_state_mismatch | all steps done; BFCL diff is RNG booking-id offset from extra get_nearest_airport call |
| 7/7 | [pilot_50_0030](pilot_50_0030.md) | `looks_success` | instance_state_mismatch | tool said canDrive=true so no fill; hidden mismatch vs GT fill of 7 |
| 7/7 | [pilot_50_0034](pilot_50_0034.md) | `looks_success` | execution_response_mismatch | all steps done; BFCL diff is RNG booking-id offset |
| 7/7 | [pilot_50_0040](pilot_50_0040.md) | `looks_success` | execution_response_mismatch | all steps done; BFCL diff is order-id offset (12447 vs 12446) |
| 7/7 | [pilot_50_0044](pilot_50_0044.md) | `genuine_visible` | instance_state_mismatch | user said ticket description empty; agent wrote a long description |
| 7/7 | [pilot_50_0046](pilot_50_0046.md) | `looks_success` | execution_response_mismatch | all done; mismatch is missing authenticate call response; insurance_type unspecified |
| 6/7 | [pilot_50_0004](pilot_50_0004.md) | `genuine_visible` | instance_state_mismatch | lockDoors(unlock="false") left doors unlocked; engine never started |
| 5/7 | [pilot_50_0032](pilot_50_0032.md) | `genuine_visible` | execution_response_mismatch | last turn: agent only announces plan, file never created |
| 5/7 | [pilot_50_0038](pilot_50_0038.md) | `genuine_visible` | instance_state_mismatch | get_flight_cost used wrong code CHI -> error; booking abandoned |
| 5/7 | [pilot_50_0048](pilot_50_0048.md) | `genuine_visible` | empty_turn_model_response | degenerate repeated calls; latest-order question unanswered |
| 5/7 | [pilot_50_0050](pilot_50_0050.md) | `genuine_visible` | empty_turn_model_response | remove Zeta from watchlist never executed; no reply |
| 4/7 | [pilot_50_0010](pilot_50_0010.md) | `genuine_visible` | instance_state_mismatch | user asked 30 gal; fill errored; agent filled 15 instead; final messages empty |
| 4/7 | [pilot_50_0036](pilot_50_0036.md) | `genuine_visible` | instance_state_mismatch | estimate_distance has no tool result; agent sent invented 832 miles |
| 3/7 | [pilot_50_0008](pilot_50_0008.md) | `looks_success` | instance_state_mismatch | tweet posted, engine running; invented credentials for authenticate_twitter (borderline) |
| 3/7 | [pilot_50_0014](pilot_50_0014.md) | `genuine_weak` | execution_response_mismatch | honest "nothing found" but task had files; mv/ticket requests also unmet |
| 3/7 | [pilot_50_0020](pilot_50_0020.md) | `genuine_visible` | empty_turn_model_response | degenerate repeated calls, no answer; fill 30 errored |
| 3/7 | [pilot_50_0042](pilot_50_0042.md) | `genuine_visible` | empty_turn_model_response | final turn startEngine/post_tweet have no tool results; empty end |
| 2/7 | [pilot_50_0022](pilot_50_0022.md) | `genuine_visible` | instance_state_mismatch | cd error, diff error, copy to Archived has no tool result |
| 2/7 | [pilot_50_0026](pilot_50_0026.md) | `genuine_visible` | instance_state_mismatch | book_flight failed (empty card_id); message to empty receiver failed |
| 1/7 | [pilot_50_0018](pilot_50_0018.md) | `genuine_visible` | empty_turn_model_response | turn0 no results; cd errors; agent says dirs do not exist |

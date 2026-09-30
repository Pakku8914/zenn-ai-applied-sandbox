import { mountCampaignCatalog } from '../CampaignCatalog';
import { reportWebVitals } from '../../../vitals';

// Good（別解）：バナーを一覧の流れに入れず、画面下に重ねて出す
mountCampaignCatalog('overlay');
reportWebVitals();

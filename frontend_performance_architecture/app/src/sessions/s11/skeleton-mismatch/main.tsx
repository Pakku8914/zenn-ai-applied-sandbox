import { mount } from '../mount';
import { SkeletonCatalog } from '../SkeletonCatalog';

// Bad：スケルトンはあるが、高さが本物と違う
mount(<SkeletonCatalog mode="mismatch" />);

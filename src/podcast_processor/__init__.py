from beartype.claw import beartype_this_package
from beartype.roar import BeartypeDecorHintPep585DeprecationWarning
from warnings import filterwarnings

beartype_this_package()

filterwarnings("ignore", category=BeartypeDecorHintPep585DeprecationWarning)

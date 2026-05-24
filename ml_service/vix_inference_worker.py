import logging
import joblib
import polars as pl
from ml.vix_pipeline import generate_macro_features

logger = logging.getLogger(__name__)

class VixRegimePredictor:
    """
    Inference worker to predict the probability of a VIX spike using
    a pre-trained XGBoost model.
    """

    def __init__(self, model_path: str = "models/xgb_vix_regime_v1.pkl"):
        """
        Initializes the predictor and attempts to load the model artifact.

        Args:
            model_path (str): The path to the serialized XGBoost model (via scikit-learn/joblib).
        """
        self.model_path = model_path
        self.model = None

        try:
            self.model = joblib.load(self.model_path)
            logger.info(f"Successfully loaded VIX prediction model from {self.model_path}")
        except FileNotFoundError:
            logger.critical(f"Model file not found at {self.model_path}. Fallback mode active (fail-safe to cash).")
        except Exception as e:
            logger.critical(f"Failed to load model from {self.model_path} due to: {e}. Fallback mode active (fail-safe to cash).")

    def predict_spike_probability(self, recent_data: pl.LazyFrame) -> float:
        """
        Predicts the probability of a volatility spike for the most recent day.

        Args:
            recent_data (pl.LazyFrame): A LazyFrame containing at least 14-30 days
                                        of 'Date', 'NIFTY_Close', and 'VIX_Close'.

        Returns:
            float: Probability (0.0 to 1.0) of a VIX spike. Returns 1.0 on failure
                   as a strict fail-safe to halt selling options.
        """
        try:
            # If model isn't loaded, immediately fail-safe to 1.0
            if self.model is None:
                logger.critical("Model is not loaded. Returning fail-safe spike probability of 1.0.")
                return 1.0

            # Generate the exact same macro features used in training via the pipeline
            feature_lf = generate_macro_features(recent_data)

            # Materialise to extract the most recent row (today's features)
            feature_df = feature_lf.collect()

            if feature_df.height == 0:
                logger.critical("Feature generation resulted in an empty DataFrame. Returning fail-safe probability of 1.0.")
                return 1.0

            # The dataframe is sorted chronologically in generate_macro_features,
            # so the tail(1) is the most recent day.
            latest_row = feature_df.tail(1)

            # Drop non-feature columns that the scikit-learn model wasn't trained on.
            # Assuming 'Date' shouldn't be passed to the model. We keep NIFTY_Close and VIX_Close
            # along with the newly generated features, assuming they were part of the training set.
            # If the original training strictly dropped NIFTY_Close/VIX_Close, we'd drop them here,
            # but usually, XGBoost handles the exact columns passed to it as long as they match training.
            if "Date" in latest_row.columns:
                latest_row = latest_row.drop("Date")

            # Convert to Pandas for compatibility with Scikit-Learn's XGBClassifier wrapper
            latest_row_pd = latest_row.to_pandas()

            # Predict probability
            # predict_proba returns an array of shape (n_samples, n_classes)
            # Typically class 0 is 'no spike', class 1 is 'spike'.
            probabilities = self.model.predict_proba(latest_row_pd)

            # Extract probability for Class 1 (Spike)
            spike_prob = float(probabilities[0][1])

            logger.info(f"Predicted VIX spike probability: {spike_prob:.4f}")
            return spike_prob

        except Exception as e:
            logger.critical(f"Inference failed during predict_spike_probability: {e}. Returning fail-safe probability of 1.0.", exc_info=True)
            return 1.0

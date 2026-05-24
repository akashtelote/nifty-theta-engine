import logging
import joblib
import polars as pl
from ml.vix_pipeline import generate_macro_features

logger = logging.getLogger(__name__)

class VixRegimePredictor:
    """
    Inference worker to predict the probability of a VIX spike using
    a pre-trained XGBoost model. The Wheel Bot will call this every day
    at 15:00 IST to get a "go/no-go" signal based on the probability.
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
            # Safely load the XGBoost model artifact into memory using joblib
            self.model = joblib.load(self.model_path)
            logger.info(f"Successfully loaded VIX prediction model from {self.model_path}")
        except FileNotFoundError:
            # Fallback mechanism if the model file is missing
            logger.critical(f"Model file not found at {self.model_path}. Fallback mode active (fail-safe to cash).")
        except Exception as e:
            # Fallback mechanism if the model file is corrupted or fails to load
            logger.critical(f"Failed to load model from {self.model_path} due to: {e}. Fallback mode active (fail-safe to cash).")

    def predict_spike_probability(self, recent_data: pl.LazyFrame) -> float:
        """
        Predicts the probability of a volatility spike for the most recent day.

        Args:
            recent_data (pl.LazyFrame): A LazyFrame containing at least 14-30 days
                                        of 'Date', 'NIFTY_Close', and 'VIX_Close' closes.

        Returns:
            float: Probability (0.0 to 1.0) of a VIX spike. Returns 1.0 on failure
                   as a strict fail-safe to halt selling options.
        """
        try:
            # If model isn't loaded (from initialization), immediately fail-safe to 1.0
            if self.model is None:
                logger.critical("Model is not loaded. Returning fail-safe spike probability of 1.0.")
                return 1.0

            # Generate the exact same macro features used in training via the pipeline
            # to ensure the live feature space perfectly matches the training feature space.
            feature_lf = generate_macro_features(recent_data)

            # Materialise the LazyFrame to trigger the lazy execution graph into memory
            feature_df = feature_lf.collect()

            if feature_df.height == 0:
                logger.critical("Feature generation resulted in an empty DataFrame. Returning fail-safe probability of 1.0.")
                return 1.0

            # Isolate the single most recent row (today's features)
            # The dataframe is sorted chronologically in generate_macro_features,
            # so the tail(1) is the most recent day.
            latest_row = feature_df.tail(1)

            # Drop non-feature columns right before model ingestion so the feature space matches perfectly.
            # We explicitly drop "Date" (and any other identifier strings).
            if "Date" in latest_row.columns:
                latest_row = latest_row.drop(["Date"])

            # Scikit-learn wrappers can be highly sensitive to Polars.
            # Explicitly convert the final 1-row DataFrame to Pandas using .to_pandas()
            # immediately before calling predict_proba().
            latest_row_pd = latest_row.to_pandas()

            # Predict probability
            # Pass this row to the loaded XGBoost model and extract the predict_proba
            # Typically predict_proba returns an array of shape (n_samples, n_classes)
            # Class 0 is 'no spike', Class 1 is 'spike'.
            probabilities = self.model.predict_proba(latest_row_pd)

            # Extract probability for Class 1 (Spike)
            spike_prob = float(probabilities[0][1])

            logger.info(f"Predicted VIX spike probability: {spike_prob:.4f}")
            # Return this probability as a float between 0.0 and 1.0
            return spike_prob

        except Exception as e:
            # If any exception occurs during inference, log a CRITICAL warning and hardcode
            # the fallback return value to 1.0 (Fail-safe to cash).
            logger.critical(f"Inference failed during predict_spike_probability: {e}. Returning fail-safe probability of 1.0.", exc_info=True)
            return 1.0
